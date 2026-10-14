// IPPure 节点信息面板 (Surge)
// 数据来源：https://my.ippure.com/v1/info（参考 StashNetworks 官方 IPPure Tile，单次请求）
// 显示：当前节点名、出口 IP、位置、运营商、ASN、IPPure 欺诈分数、IP 类型
//
// 节点名选中逻辑（参考 node_purity.js）：
//  用 Surge 内置 $httpAPI 直接调本地 HTTP API，不需要密钥：
//   1. GET /v1/outbound 看当前出站模式：direct 显示直连，global 则跟 GLOBAL 组
//   2. GET /v1/policy_groups/select?group_name=组名 拿该组当前选中项
//   3. 如果选中项还是个策略组（嵌套组），循环往下追，直到追到真正的节点
//  最后 IP 查询带 policy=节点名，强制走该节点查出口 IP
//
// 参数（argument，三选一，越往上优先级越高）：
//  node=xxx：手动写死节点名，直接显示
//  group=策略组名：实时读取该组当前选中节点（默认 Proxy）
//  纯名字，如 argument=Proxy：等同于 group=Proxy

var IPPURE_URL = "https://my.ippure.com/v1/info";
var IPAPI_URL = "http://ip-api.com/json/?fields=status,query,country,countryCode,regionName,city,isp,as";

function getArg(key) {
  if (typeof $argument !== "string" || !$argument) return "";
  var pairs = $argument.split("&");
  for (var i = 0; i < pairs.length; i++) {
    var idx = pairs[i].indexOf("=");
    if (idx > 0 && pairs[i].slice(0, idx) === key) {
      try {
        return decodeURIComponent(pairs[i].slice(idx + 1));
      } catch (e) {
        return pairs[i].slice(idx + 1);
      }
    }
  }
  return "";
}

function fetchJSON(url, timeout, policy) {
  return new Promise(function (resolve, reject) {
    var opts = { url: url, timeout: timeout || 5, headers: { "User-Agent": "Surge" } };
    if (policy) opts.policy = policy;
    $httpClient.get(opts, function (err, resp, data) {
      if (err) return reject(err);
      try {
        resolve(JSON.parse(data));
      } catch (e) {
        reject(e);
      }
    });
  });
}

// $httpAPI 封装：Surge 内置 API，调本地 HTTP API 不需要密钥
function httpAPI(path) {
  return new Promise(function (resolve) {
    $httpAPI("GET", path, null, function (result) {
      resolve(result);
    });
  });
}

// 跟随嵌套策略组链，直到解析出真正的节点名
function followGroupChain(name, allGroups) {
  if (!name || allGroups.indexOf(name) === -1) return Promise.resolve(name);
  return httpAPI("/v1/policy_groups/select?group_name=" + encodeURIComponent(name)).then(function (next) {
    if (!next || !next.policy) return name;
    return followGroupChain(next.policy, allGroups);
  });
}

// 解析当前节点：返回 { name 显示名, policy 强制走该节点的策略名 }
function resolveNode(targetGroup) {
  if (typeof $httpAPI !== "function") return Promise.resolve({ name: targetGroup, policy: "" });
  return httpAPI("/v1/outbound")
    .then(function (outbound) {
      var mode = outbound && outbound.mode;
      if (mode === "direct") return { name: "直连模式 (Direct)", policy: "DIRECT" };
      var activeGroup = mode === "global" ? "GLOBAL" : targetGroup;
      return httpAPI("/v1/policy_groups").then(function (proxy) {
        var allGroups = proxy ? Object.keys(proxy) : [];
        return httpAPI("/v1/policy_groups/select?group_name=" + encodeURIComponent(activeGroup)).then(function (sel) {
          var name = sel && sel.policy ? sel.policy : "";
          return followGroupChain(name, allGroups).then(function (finalName) {
            if (mode === "global") return { name: finalName ? "全局: " + finalName : "", policy: finalName };
            return { name: finalName, policy: finalName };
          });
        });
      });
    })
    .catch(function () { return { name: targetGroup, policy: "" }; });
}

// IP 打码：只显示前两段，后面用 * 代替
// IPv4：38.102.232.152 → 38.102.*.*
// IPv6：2406:840:... → 2406:840:*:*:*:*:*:*
function maskIP(ip) {
  if (typeof ip !== "string" || !ip) return ip;
  if (ip.indexOf(":") !== -1) {
    var g = ip.split(":");
    return g.slice(0, 2).join(":") + ":*:*:*:*:*:*";
  }
  var o = ip.split(".");
  if (o.length === 4) return o[0] + "." + o[1] + ".*.*";
  return ip;
}

function flagEmoji(code) {
  if (typeof code !== "string" || code.length !== 2) return "";
  var cc = code.toUpperCase() === "TW" ? "CN" : code.toUpperCase();
  if (!/^[A-Z]{2}$/.test(cc)) return "";
  return String.fromCodePoint(127397 + cc.charCodeAt(0), 127397 + cc.charCodeAt(1));
}

// 欺诈分数分级沿用 IPPure 自己的口径：0-25 安全，26-50 轻度风险，51-70 中度风险，71-100 高度风险
function fraudMeta(score) {
  if (score <= 25) return { tag: "安全", emoji: "🟢", color: "#34C759" };
  if (score <= 50) return { tag: "轻度风险", emoji: "🟡", color: "#FFCC00" };
  if (score <= 70) return { tag: "中度风险", emoji: "🟠", color: "#FF9500" };
  return { tag: "高度风险", emoji: "🔴", color: "#FF3B30" };
}

function finish(lines, color) {
  $done({
    title: "节点信息",
    content: lines.filter(Boolean).join("\n"),
    icon: "globe.asia.australia",
    "icon-color": color || "#3D90ED"
  });
}

function fail(err) {
  $done({
    title: "节点信息",
    content: "查询失败：" + (err && err.message ? err.message : err),
    icon: "xmark.circle",
    "icon-color": "#FF3B30"
  });
}

function buildLocation(flag, country, region, city) {
  var loc = (flag ? flag + " " : "") + (country || "");
  if (region) loc += " · " + region;
  if (city) loc += " " + city;
  return loc;
}

function renderIPPure(nodeName, p) {
  var lines = [];
  if (nodeName) lines.push("节点：" + nodeName);
  if (p.ip) lines.push("IP：" + maskIP(p.ip));
  if (p.country) lines.push("位置：" + buildLocation(flagEmoji(p.countryCode), p.country, p.region, p.city));
  if (p.asOrganization) lines.push("运营商：" + p.asOrganization);
  if (p.asn) lines.push("ASN：AS" + p.asn);

  var color = "#3D90ED";
  var score = Number(p.fraudScore);
  if (!isNaN(score)) {
    var m = fraudMeta(score);
    color = m.color;
    lines.push("欺诈分数：" + score + " " + m.emoji + " " + m.tag);
  } else {
    lines.push("欺诈分数：查询失败");
  }

  var types = [];
  if (p.isResidential) types.push("住宅");
  if (p.isBroadcast) types.push("广播");
  if (p.isDataCenter) types.push("机房");
  if (types.length) lines.push("类型：" + types.join(" / ") + " IP");

  finish(lines, color);
}

function renderIPApi(nodeName, a) {
  // IPPure 失败时用 ip-api.com 兜底 IP 与位置，欺诈分数显示查询失败
  var lines = [];
  if (nodeName) lines.push("节点：" + nodeName);
  if (a.query) lines.push("IP：" + maskIP(a.query));
  if (a.country) lines.push("位置：" + buildLocation(flagEmoji(a.countryCode), a.country, a.regionName, a.city));
  if (a.isp) lines.push("运营商：" + a.isp);
  if (a.as) lines.push("ASN：" + a.as);
  lines.push("欺诈分数：查询失败");
  finish(lines, "#3D90ED");
}

var manualNode = getArg("node");
var groupArg = getArg("group");
var bareName = (typeof $argument === "string" && $argument && $argument.indexOf("=") === -1) ? $argument : "";
var targetGroup = groupArg || bareName || "Proxy";

var nodeTask = manualNode
  ? Promise.resolve({ name: manualNode, policy: manualNode })
  : resolveNode(targetGroup);

nodeTask.then(function (node) {
  // 先解析节点，再带 policy 强制走该节点查出口 IP
  return fetchJSON(IPPURE_URL, 5, node.policy)
    .then(function (p) { renderIPPure(node.name, p); })
    .catch(function () {
      return fetchJSON(IPAPI_URL, 5, node.policy)
        .then(function (a) { renderIPApi(node.name, a); })
        .catch(fail);
    });
});
