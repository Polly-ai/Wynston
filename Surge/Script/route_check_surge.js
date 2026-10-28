// 节点去程速览（Surge 面板脚本）
//
// 能力边界，先说清楚：Surge 脚本沙箱和 HTTP API 里都没有 traceroute 接口，
// 脚本只能发 HTTP 请求，所以逐跳路由（每一跳的 IP）在这个模块里是做不出来的，
// 这是平台限制，不是代码问题。真要看每一跳，得在有控制权的 VPS 上跑 mtr，
// 或在 Mac + Surge 系统代理下用终端 mtr。
//
// 这个面板是脚本能做到的上限：当前节点 + 出口信息 + 到关键目标的延迟。
//
// 工作方式：
// 1. $surge.selectGroupDetails() 拿到当前选中的节点（拿不到时读全局出站策略）
// 2. $httpClient 以 policy=<节点名> 强制走该节点，查出口 IP 信息
// 3. 同样强制走该节点，测 3 个 204 端点的延迟
// IP 显示按惯例只留前两段。

var IP_API = 'http://ip-api.com/json/?fields=status,message,country,regionName,city,isp,org,as,query';
var TARGETS = [
  { name: '国内', url: 'http://connect.rom.miui.com/generate_204' },
  { name: 'CF', url: 'http://cp.cloudflare.com/generate_204' },
  { name: '谷歌', url: 'http://www.gstatic.com/generate_204' },
];
var ICON = 'network';
var ICON_COLOR = '#3D90ED';

function maskIP(ip) {
  if (!ip) return '未知';
  var v4 = ip.split('.');
  if (v4.length === 4) return v4[0] + '.' + v4[1] + '.x.x';
  var v6 = ip.split(':');
  if (v6.length > 2) return v6[0] + ':' + v6[1] + '::xxxx';
  return ip;
}

// 当前节点：优先 $argument 指定的策略组，其次叫 Proxy 的组，否则取第一个有选择的组
function currentNode() {
  try {
    var details = $surge.selectGroupDetails();
    var decisions = details.decisions || {};
    var names = Object.keys(decisions);
    if (typeof $argument !== 'undefined' && $argument && decisions[$argument]) {
      return decisions[$argument];
    }
    for (var i = 0; i < names.length; i++) {
      if (names[i].toLowerCase() === 'proxy') {
        return decisions[names[i]];
      }
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

resolveNode(function (nodeName) {
  var policy = nodeName;
  var displayName = nodeName || '默认出站';
  var pending = 1 + TARGETS.length;
  var egress = null;
  var lat = {};
  var finished = false;

  function finish() {
    if (finished) return;
    finished = true;
    var lines = [];
    lines.push('节点：' + displayName);
    if (egress) {
      lines.push('出口：' + egress.ip + ' | ' + egress.loc);
      lines.push('线路：' + egress.isp + (egress.asn ? ' | ' + egress.asn : ''));
    } else {
      lines.push('出口：查询失败');
    }
    var latParts = TARGETS.map(function (t) {
      return t.name + ' ' + (lat[t.name] || '失败');
    });
    lines.push('延迟：' + latParts.join(' · '));
    $done({
      title: '节点去程',
      content: lines.join('\n'),
      icon: ICON,
      'icon-color': ICON_COLOR,
    });
  }

  function checkDone() {
    if (--pending <= 0) finish();
  }

  $httpClient.get(getOpts(IP_API, policy), function (error, response, data) {
    try {
      var j = JSON.parse(data);
      if (j && j.status === 'success') {
        egress = {
          ip: maskIP(j.query),
          loc: [j.country, j.regionName, j.city].filter(function (x) { return !!x; }).join(' '),
          isp: j.isp || j.org || '未知',
          asn: j.as || '',
        };
      }
    } catch (e) {}
    checkDone();
  });

  TARGETS.forEach(function (t) {
    var start = Date.now();
    $httpClient.get(getOpts(t.url, policy), function (error, response, data) {
      lat[t.name] = error ? '失败' : (Date.now() - start) + 'ms';
      checkDone();
    });
  });
});
