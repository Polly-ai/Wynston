// 节点去程路径（Surge 面板脚本 v2）
//
// 显示目标：去程怎么走、有没有绕路，不是延迟。
// 面板卡片装不下 16 行完整跳数表，所以这里显示压缩版：
// 国家/网络路径序列 + 绕路结论。完整跳数见原始追踪，不在面板里展开。
//
// 数据来源：Globalping 公开免费接口（免 key，纯 REST：POST 建任务 + 轮询取结果）。
// 为什么不用 itdog：itdog 是非官方接口，要先 POST 建任务再 WebSocket 收结果，
// 还要一个站内 md5 token，在 Surge 面板里实现脆弱且容易失效；
// Globalping 已实测跑通（国内探针追踪 SG 目标，16 秒出结果）。
// 监测点是 Globalping 在国内在线的探针（当前只有长沙联通这一个），
// 不是按运营商/省份自选；探针不在线时会直接提示。
//
// 工作方式：
// 1. 当前节点（选中策略组决定，拿不到时读全局出站策略）
// 2. 经该节点查出口 IP（ip-api），这个 IP 就是追踪目标（VPS 节点出口即服务器 IP）
// 3. Globalping 从国内探针追踪该 IP，取 hops
// 4. 每跳 IP 用 $utils.geoip 取国家，连续相同国家合并成路径序列；
//    终点国家之外的途经国家 = 绕路
// IP 显示按惯例只留前两段。

var IP_API = 'http://ip-api.com/json/?fields=status,message,country,regionName,city,isp,org,as,query';
var GP_CREATE = 'https://api.globalping.io/v1/measurements';
var ICON = 'network';
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
    title: '节点去程',
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
    try {
      var j = JSON.parse(data);
      if (j && j.status === 'success') {
        target = j.query;
        var loc = [j.country, j.regionName, j.city].filter(function (x) { return !!x; }).join(' ');
        egressLine = '出口：' + maskIP(j.query) + (loc ? ' | ' + loc : '');
      }
    } catch (e) {}
    if (!target) {
      finish(['节点：' + displayName, egressLine, '路径：出口查不到，无法追踪']);
      return;
    }
    // 第二步：Globalping 建任务（这一步不走节点，直连即可）
    $httpClient.post({
      url: GP_CREATE,
      body: {
        type: 'traceroute',
        target: target,
        locations: [{ country: 'CN' }],
        measurementOptions: { protocol: 'ICMP' },
      },
      timeout: 10,
    }, function (error2, response2, data2) {
      var id = null;
      var probesCount = -1;
      try {
        var r = JSON.parse(data2);
        id = r.id;
        probesCount = r.probesCount;
      } catch (e) {}
      if (!id) {
        finish(['节点：' + displayName, egressLine, '路径：追踪任务创建失败']);
        return;
      }
      if (probesCount === 0) {
        finish(['节点：' + displayName, egressLine, '路径：国内暂无探针在线']);
        return;
      }
      poll(id, 0, displayName, egressLine);
    });
  });

  function poll(id, attempt, displayName, egressLine) {
    if (attempt >= POLL_MAX) {
      finish([ '节点：' + displayName, egressLine, '路径：追踪超时（探针未返回）']);
      return;
    }
    $httpClient.get({ url: GP_CREATE + '/' + id, timeout: 10 }, function (error, response, data) {
      var status = '';
      var first = null;
      try {
        var r = JSON.parse(data);
        status = r.status;
        first = r.results && r.results[0];
      } catch (e) {}
      if (status === 'finished' && first && first.result) {
        render(first, displayName, egressLine);
        return;
      }
      if (status === 'failed') {
        finish(['节点：' + displayName, egressLine, '路径：探针追踪失败']);
        return;
      }
      setTimeout(function () { poll(id, attempt + 1, displayName, egressLine); }, POLL_INTERVAL);
    });
  }

  function render(first, displayName, egressLine) {
    var probe = first.probe || {};
    var hops = (first.result && first.result.hops) || [];
    var monitor = (probe.city || '国内') + (carrierOf(probe.network) || '');
    var seq = [];
    var hopCount = 0;
    for (var i = 0; i < hops.length; i++) {
      var h = hops[i];
      var ip = h.resolvedAddress;
      if (!ip || isPrivateIP(ip)) continue;
      hopCount++;
      var c = countryOf(ip, h.resolvedHostname);
      if (c && (seq.length === 0 || seq[seq.length - 1] !== c)) seq.push(c);
    }
    var dest = seq.length > 0 ? seq[seq.length - 1] : null;
    var transit = [];
    for (var k = 0; k < seq.length; k++) {
      if (seq[k] !== '中国' && seq[k] !== dest && transit.indexOf(seq[k]) === -1) transit.push(seq[k]);
    }
    var lines = [];
    lines.push('节点：' + displayName);
    lines.push(egressLine);
    lines.push('监测点：' + monitor);
    if (seq.length === 0) {
      lines.push('路径：无可用跳数');
    } else {
      lines.push('路径：' + seq.join(' → ') + '（' + hopCount + ' 跳）');
      if (transit.length > 0) lines.push('结论：⚠️ 绕路（经' + transit.join('、') + '）');
      else lines.push('结论：直连，无绕路');
    }
    finish(lines);
  }
});
