// 路由追踪（Surge 面板脚本 v4）
//
// 显示目标：去程怎么走、有没有绕路，落地点在哪，不是延迟。
// 面板卡片装不下 16 行完整跳数表，所以这里显示压缩版：
// 路径按（国家 + ASN）分段，落地单独一行，结论只在追踪到终点时才下。
//
// v2 的教训：追踪没到终点时，路径只剩中国几跳，结论却写了“直连”——
// 那是错的。v3 起先核对最后一跳是不是目标 IP，没到终点就明说未到终点，
// 不下直连/绕路的结论。
//
// v4 对“未知”的处理：骨干网路由器（如电信 202.97 段）在 Surge 自带 IP 库里
// 常常没有地理位置，geoip 返回空。处理分三档：终点那跳直接用 ip-api 的
// 国家；同 ASN 的未知跳继承上一段的国家（同属一家骨干网）；其他未知跳
// 显示运营商名（如 RETN AS9002），实在没名才写未知。
//
// 数据来源：Globalping 公开免费接口（免 key，纯 REST：POST 建任务 + 轮询取结果）。
// 监测点首选陕西电信（西安 4134），不在线时依次退到国内电信、国内任意探针；
// 监测点那行永远显示实际用的探针。社区探针上下线频繁，陕西电信探针不在线
// 时面板会用其他探针顶上并如实标注，不是偷偷换。
var LOCATIONS_CHAIN = [
  [{ country: 'CN', city: "Xi'an", asn: 4134 }],
  [{ country: 'CN', asn: 4134 }],
  [{ country: 'CN' }],
];
var CITY_NAMES = {
  "Xi'an": '西安', Shanghai: '上海', Changsha: '长沙', Guangzhou: '广州',
  Beijing: '北京', Shenzhen: '深圳', Chengdu: '成都', Wuhan: '武汉',
  Nanjing: '南京', Hangzhou: '杭州', Zhengzhou: '郑州', Nanning: '南宁',
  // ip-api 的节点城市（英文 -> 中文；查不到的城市原样显示英文）
  'Frankfurt am Main': '法兰克福', 'Los Angeles': '洛杉矶', Singapore: '新加坡',
  Tokyo: '东京', Osaka: '大阪', 'San Jose': '圣何塞', Seattle: '西雅图',
  Amsterdam: '阿姆斯特丹', London: '伦敦', Sydney: '悉尼', Seoul: '首尔',
  'Hong Kong': '香港', Taipei: '台北', Mumbai: '孟买', Toronto: '多伦多',
  Chicago: '芝加哥', Dallas: '达拉斯', Miami: '迈阿密', 'New York': '纽约',
  'San Francisco': '旧金山', Ashburn: '阿什本', 'Salt Lake City': '盐湖城',
};

// 工作方式：
// 1. 当前节点（选中策略组决定，拿不到时读全局出站策略）
// 2. 经该节点查出口 IP（ip-api），这个 IP 就是追踪目标（VPS 节点出口即服务器 IP）
// 3. Globalping 从国内探针追踪该 IP，取 hops
// 4. 每跳 IP 用 $utils.geoip 取国家、$utils.ipasn 取 ASN，连续相同（国家+ASN）
//    合并成一段；终点国家之外的途经国家 = 绕路
// IP 显示按惯例只留前两段。

var IP_API = 'http://ip-api.com/json/?fields=status,message,country,countryCode,city,isp,org,as,query';
var GP_CREATE = 'https://api.globalping.io/v1/measurements';
var ICON = 'point.topleft.down.to.point.bottomright.curvepath';
var ICON_COLOR = '#3D90ED';
var POLL_INTERVAL = 5000;
var POLL_MAX = 10;

var COUNTRY_NAMES = {
  CN: '中国', US: '美国', SG: '新加坡', JP: '日本', DE: '德国',
  GB: '英国', KR: '韩国', HK: '香港', TW: '台湾', AU: '澳大利亚',
  NL: '荷兰', FR: '法国', CA: '加拿大', IN: '印度', BR: '巴西',
};
// 数据中心城市代码 -> 国家（hostname 里常见，如 lax2.he.net、sin1.he.net）
var HOST_HINTS = {
  lax: '美国', sin: '新加坡', sgp: '新加坡', tyo: '日本', hnd: '日本',
  fra: '德国', ams: '荷兰', lhr: '英国', syd: '澳大利亚', icn: '韩国',
  hkg: '香港', ord: '美国', dfw: '美国', mia: '美国', sea: '美国',
  sjc: '美国', ash: '美国', tor: '加拿大', bom: '印度', gru: '巴西',
};
// 国家查不到时的运营商名（只列把握大的知名 ASN）
var ASN_ORG = {
  4134: '中国电信', 4837: '中国联通', 9808: '中国移动', 9929: '联通产业互联',
  9002: 'RETN', 6939: 'HE', 174: 'Cogent', 1299: 'Telia', 3356: 'Lumen',
  3491: 'PCCW', 2914: 'NTT', 45090: '腾讯云', 37963: '阿里云', 55990: '华为云',
};

function maskIP(ip) {
  if (!ip) return '未知';
  var v4 = ip.split('.');
  if (v4.length === 4) return v4[0] + '.' + v4[1] + '.x.x';
  var v6 = ip.split(':');
  if (v6.length > 2) return v6[0] + ':' + v6[1] + '::xxxx';
  return ip;
}

function isPrivateIP(ip) {
  if (!ip) return true;
  var p = ip.split('.');
  if (p.length !== 4) return false;
  var a = parseInt(p[0], 10), b = parseInt(p[1], 10);
  if (a === 10) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  if (a === 100 && b >= 64 && b <= 127) return true;
  return false;
}

function countryOf(ip, hostname) {
  var code = null;
  try { code = $utils.geoip(ip); } catch (e) {}
  if (code && COUNTRY_NAMES[code]) return COUNTRY_NAMES[code];
  if (code) return code;
  // geoip 查不到时，用 hostname 里的城市代码推断
  if (hostname) {
    var h = hostname.toLowerCase();
    for (var k in HOST_HINTS) {
      if (h.indexOf(k) !== -1) return HOST_HINTS[k];
    }
  }
  return null;
}

function asnOf(ip) {
  try {
    var asn = $utils.ipasn(ip);
    if (asn !== null && asn !== undefined && asn !== '') return String(asn);
  } catch (e) {}
  return null;
}

function carrierOf(network) {
  if (!network) return '';
  var n = network.toUpperCase();
  if (n.indexOf('UNICOM') !== -1) return '联通';
  if (n.indexOf('TELECOM') !== -1 || n.indexOf('CHINANET') !== -1) return '电信';
  if (n.indexOf('MOBILE') !== -1) return '移动';
  return '';
}

function currentNode() {
  try {
    var details = $surge.selectGroupDetails();
    var decisions = details.decisions || {};
    var names = Object.keys(decisions);
    if (typeof $argument !== 'undefined' && $argument && decisions[$argument]) {
      return decisions[$argument];
    }
    for (var i = 0; i < names.length; i++) {
      if (names[i].toLowerCase() === 'proxy') return decisions[names[i]];
    }
    if (names.length > 0) return decisions[names[0]];
  } catch (e) {}
  return '';
}

// 拿不到选中节点时，读全局出站策略（global 模式下用这个）
function resolveNode(cb) {
  var node = currentNode();
  if (node) { cb(node); return; }
  try {
    $httpAPI('GET', '/v1/outbound/global', {}, function (result) {
      if (result && result.policy) cb(result.policy);
      else cb('');
    });
  } catch (e) { cb(''); }
}

function getOpts(url, policy) {
  var o = { url: url, timeout: 5 };
  if (policy) o.policy = policy;
  return o;
}

function finish(lines) {
  $done({
    title: '路由追踪',
    content: lines.join('\n'),
    icon: ICON,
    'icon-color': ICON_COLOR,
  });
}

resolveNode(function (nodeName) {
  var policy = nodeName;
  var displayName = nodeName || '默认出站';

  // 第一步：经节点查出口 IP，作为追踪目标
  $httpClient.get(getOpts(IP_API, policy), function (error, response, data) {
    var target = null;
    var egressLine = '出口：查询失败';
    var egress = { loc: '', asn: '', countryCn: '' };
    try {
      var j = JSON.parse(data);
      if (j && j.status === 'success') {
        target = j.query;
        egress.countryCn = COUNTRY_NAMES[j.countryCode] || j.country || '';
        var cityCn = CITY_NAMES[j.city] || j.city || '';
        egress.loc = [egress.countryCn, cityCn].filter(function (x) { return !!x; }).join(' ');
        egress.asn = (j.as || '').split(' ')[0];
        egressLine = '出口：' + maskIP(j.query) + (egress.loc ? ' | ' + egress.loc : '');
      }
    } catch (e) {}
    if (!target) {
      finish(['节点：' + displayName, egressLine, '路径：出口查不到，无法追踪']);
      return;
    }
    // 第二步：Globalping 建任务。注意：建任务和轮询都走节点（policy），不直连——
    // api.globalping.io 从国内直连不稳定（v2 实测建任务失败），走节点更稳；
    // 探针选择在服务端按 locations 定，不影响追踪起点。
    // 按 LOCATIONS_CHAIN 依次尝试，首选陕西电信
    var ctx = { displayName: displayName, egressLine: egressLine, egress: egress, target: target, policy: policy };
    var apiReachable = false;
    (function tryCreate(i) {
      if (i >= LOCATIONS_CHAIN.length) {
        finish(['节点：' + displayName, egressLine, apiReachable ? '路径：国内暂无探针在线' : '路径：Globalping 接口无响应']);
        return;
      }
      $httpClient.post({
        url: GP_CREATE,
        body: {
          type: 'traceroute',
          target: target,
          locations: LOCATIONS_CHAIN[i],
          measurementOptions: { protocol: 'ICMP' },
        },
        policy: ctx.policy,
        timeout: 20,
      }, function (error2, response2, data2) {
        var id = null;
        var probesCount = -1;
        try {
          var r = JSON.parse(data2);
          apiReachable = true;
          id = r.id;
          probesCount = r.probesCount;
        } catch (e) {}
        if (id && probesCount > 0) {
          poll(id, 0, ctx);
        } else {
          tryCreate(i + 1);
        }
      });
    })(0);
  });

  function poll(id, attempt, ctx) {
    if (attempt >= POLL_MAX) {
      finish(['节点：' + ctx.displayName, ctx.egressLine, '路径：追踪超时（探针未返回）']);
      return;
    }
    $httpClient.get({ url: GP_CREATE + '/' + id, policy: ctx.policy, timeout: 15 }, function (error, response, data) {
      var status = '';
      var first = null;
      try {
        var r = JSON.parse(data);
        status = r.status;
        first = r.results && r.results[0];
      } catch (e) {}
      if (status === 'finished' && first && first.result) {
        render(first, ctx);
        return;
      }
      if (status === 'failed') {
        finish(['节点：' + ctx.displayName, ctx.egressLine, '路径：探针追踪失败']);
        return;
      }
      setTimeout(function () { poll(id, attempt + 1, ctx); }, POLL_INTERVAL);
    });
  }

  function render(first, ctx) {
    var probe = first.probe || {};
    var hops = (first.result && first.result.hops) || [];
    var monitor = (CITY_NAMES[probe.city] || probe.city || '国内') + (carrierOf(probe.network) || '');
    var segs = []; // {key, label, country}
    var hopCount = 0;
    var lastIdx = 0;
    var lastCountry = null;
    var reached = false;
    var finalRTT = null;
    for (var i = 0; i < hops.length; i++) {
      var h = hops[i];
      var ip = h.resolvedAddress;
      if (!ip) continue;
      lastIdx = i + 1;
      if (isPrivateIP(ip)) continue;
      hopCount++;
      var isTarget = (ip === ctx.target);
      var c = countryOf(ip, h.resolvedHostname);
      // 终点那跳：geoip 常常查不到，直接用 ip-api 的国家
      if (isTarget && ctx.egress.countryCn) c = ctx.egress.countryCn;
      var asn = asnOf(ip);
      // 同 ASN 的未知跳：继承上一段的国家（同属一家骨干网，如电信 202.97 段）
      var prev = segs.length > 0 ? segs[segs.length - 1] : null;
      if (!c && asn && prev && prev.asn === asn && prev.country) c = prev.country;
      var label;
      if (c) {
        label = c;
        if (asn) label += 'AS' + asn;
      } else if (asn && ASN_ORG[asn]) {
        label = ASN_ORG[asn] + ' AS' + asn;
      } else {
        label = '未知';
        if (asn) label += 'AS' + asn;
      }
      var key = (c || '?') + '|' + (asn || '');
      if (segs.length === 0 || segs[segs.length - 1].key !== key) {
        segs.push({ key: key, label: label, country: c, asn: asn });
      }
      lastCountry = c || lastCountry;
      if (isTarget) {
        reached = true;
        if (h.timings && h.timings.length > 0 && h.timings[0].rtt !== undefined) {
          finalRTT = Math.round(h.timings[0].rtt);
        }
      }
    }
    var lines = [];
    lines.push('节点：' + ctx.displayName);
    lines.push(ctx.egressLine);
    lines.push('监测点：' + monitor);
    lines.push('────────────────');
    if (segs.length === 0) {
      lines.push('路径：无可用跳数');
      lines.push('落地：未到达');
      lines.push('结论：无数据');
      finish(lines);
      return;
    }
    var pathLine = '路径：' + segs.map(function (s) { return s.label; }).join(' → ') + '（' + hopCount + ' 跳）';
    if (!reached) pathLine += '，未到终点';
    lines.push(pathLine);
    if (reached) {
      var land = '落地：' + maskIP(ctx.target) + ' | ' + (ctx.egress.loc || '') + (ctx.egress.asn ? ' ' + ctx.egress.asn : '') + (finalRTT !== null ? ' | ' + finalRTT + 'ms' : '');
      lines.push(land);
      var dest = segs[segs.length - 1].country;
      var transit = [];
      for (var k = 0; k < segs.length; k++) {
        var cc = segs[k].country;
        if (cc && cc !== '中国' && cc !== dest && transit.indexOf(cc) === -1) transit.push(cc);
      }
      lines.push(transit.length > 0 ? '结论：⚠️ 绕路（经' + transit.join('、') + '）' : '结论：✅ 直连，无绕路');
    } else {
      lines.push('落地：未到达（最后响应第 ' + lastIdx + ' 跳 · ' + (lastCountry || '未知') + '）');
      lines.push('结论：⏳ 追踪未到终点，结论仅供参考');
    }
    finish(lines);
  }
});
