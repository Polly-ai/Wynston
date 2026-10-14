// IPPure 节点信息面板 (Surge)
// 数据来源：https://my.ippure.com/v1/info（参考 StashNetworks 官方 IPPure Tile，单次请求）
// 显示（对齐 IPPure 网站详情页）：标题即节点名；内容为 ASN、位置、宽带、机构、IP来源、IP属性、IPPure系数（不显示 IP）
// 网站有但 /v1/info 接口不返回的（AS域名、IP范围、人机流量比、多源位置）无法显示
// 宽带取 ip-api.com 的 isp、机构取 ip-api.com 的 org（同 node_purity.js）；宽带无结果时回落到 IPPure 的 asOrganization，机构无结果时不显示；与 IPPure 并行查询
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
var IPAPI_URL = "http://ip-api.com/json/?fields=status,query,country,countryCode,regionName,city,isp,org,as,mobile,hosting";

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

// 系数分级沿用 IPPure 自己的口径：0-25 纯净，26-50 轻度风险，51-70 中度风险，71-100 高度风险
function fraudMeta(score) {
  if (score <= 25) return { tag: "纯净", emoji: "🟢", color: "#34C759" };
  if (score <= 50) return { tag: "轻度风险", emoji: "🟡", color: "#FFCC00" };
  if (score <= 70) return { tag: "中度风险", emoji: "🟠", color: "#FF9500" };
  return { tag: "高度风险", emoji: "🔴", color: "#FF3B30" };
}

function finish(lines, color, icon, title) {
  $done({
    title: title || "节点信息",
    content: lines.filter(function (l) { return l !== undefined && l !== null; }).join("\n"),
    icon: icon || "globe.asia.australia",
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

function buildLocation(country, region, city) {
  var loc = country || "";
  if (region) loc += " · " + region;
  if (city) loc += " · " + city;
  return loc;
}


// 运营商名去冗余后缀：Cogent Communications, LLC → Cogent Communications
function cleanOrg(name) {
  if (typeof name !== "string") return name;
  return name.replace(/,?\s*(LLC|Inc|Corp|Ltd|Limited|Company|Co\.?\s*Ltd\.?|Co\.?)\.?$/i, "").trim();
}

function renderIPPure(nodeName, p, a) {
  var details = [];
  // ASN：ASxxxx – 运营商（同网站格式，运营商去冗余后缀）
  var asnOrg = cleanOrg(p.asOrganization);
  var asnLine = "";
  if (p.asn) asnLine = "AS" + p.asn;
  if (asnOrg) asnLine = asnLine ? asnLine + " – " + asnOrg : asnOrg;
  if (asnLine) details.push("ASN：" + asnLine);
  if (p.country) details.push("位置：" + buildLocation(p.country, p.region, p.city));
  // 宽带：运营商名（同 node_purity.js 的“宽带”，取 ip-api 的 isp；无结果时回落到 IPPure 的 asOrganization）
  // 与 ASN 行运营商重复时不显示，避免同一名字出现多次
  var ispName = (a && a.isp) ? cleanOrg(a.isp) : asnOrg;
  if (ispName && ispName !== asnOrg) details.push("宽带：" + ispName);
  // 机构：同 node_purity.js 的“机构”，取 ip-api 的 org；与宽带/ASN 运营商重复时不显示
  var orgName = (a && a.org) ? cleanOrg(a.org) : "";
  if (orgName && orgName !== ispName && orgName !== asnOrg) details.push("机构：" + orgName);
  // IP来源：原生 / 广播（网站叫法，由 isBroadcast 决定）
  if (typeof p.isBroadcast === "boolean") details.push("IP来源：" + (p.isBroadcast ? "📡 广播IP" : "✅ 原生IP"));
  // IP属性：移动 / 住宅 / 机房（网站叫法，单值；移动优先，同 node_purity.js）
  var attr = "";
  if (a && a.mobile) attr = "📱 移动网络";
  else if (p.isResidential) attr = "🏠 住宅IP";
  else if (p.isDataCenter) attr = "🖥️ 机房IP";
  else if (p.isBroadcast) attr = "📡 广播IP";
  if (attr) details.push("IP属性：" + attr);

  var color = "#3D90ED";
  var coefLine = "";
  // 系数优先用 ippureCoefficient（即网站的 IPPure系数），缺失时回落到 fraudScore
  var score = Number(p.ippureCoefficient);
  if (isNaN(score)) score = Number(p.fraudScore);
  if (!isNaN(score)) {
    var m = fraudMeta(score);
    color = m.color;
    coefLine = "IPPure系数：" + score + "% " + m.emoji + " " + m.tag;
  } else if (p.ip && p.ip.indexOf(":") !== -1) {
    // 已实测：IPPure 的 IPv6 响应里本来就没有分数，不是查询失败
    coefLine = "IPPure系数：" + "v6 无分数（IPPure 仅给 v4 打分）";
  } else {
    coefLine = "IPPure系数：" + "查询失败";
  }

  // 图标：纯净或无分数时按 IP 属性适配（住宅房子/机房机架/广播天线/未知地球）；
  // 轻度风险以上按风险适配（轻/中度黄橙三角、高度红八角），颜色始终跟系数风险走
  var icon;
  if (!isNaN(score) && score > 25) {
    icon = score <= 70 ? "exclamationmark.triangle.fill" : "exclamationmark.octagon.fill";
  } else {
    icon = "globe.asia.australia";
    if (p.isResidential) icon = "house.fill";
    else if (p.isDataCenter) icon = "server.rack";
    else if (p.isBroadcast) icon = "antenna.radiowaves.left.and.right";
  }

  // 排版：标题即节点名；内容以空行开头，详情 / 系数两段空行分隔
  var lines = [""].concat(details);
  if (details.length) lines.push("");
  lines.push(coefLine);

  finish(lines, color, icon, nodeName);
}

function renderIPApi(nodeName, a) {
  // IPPure 失败时用 ip-api.com 兜底位置等信息，系数显示查询失败
  var details = [];
  var fallbackAsnOrg = "";
  if (a.as) {
    var am = a.as.match(/^(AS\d+)\s+(.*)$/);
    fallbackAsnOrg = am ? cleanOrg(am[2]) : "";
    details.push("ASN：" + (am ? am[1] + (fallbackAsnOrg ? " – " + fallbackAsnOrg : "") : a.as));
  }
  if (a.country) details.push("位置：" + buildLocation(a.country, a.regionName, a.city));
  var fallbackIsp = a.isp ? cleanOrg(a.isp) : "";
  if (fallbackIsp && fallbackIsp !== fallbackAsnOrg) details.push("宽带：" + fallbackIsp);
  var fallbackOrg = a.org ? cleanOrg(a.org) : "";
  if (fallbackOrg && fallbackOrg !== fallbackIsp && fallbackOrg !== fallbackAsnOrg) details.push("机构：" + fallbackOrg);
  if (a.mobile) details.push("IP属性：" + "📱 移动网络");
  else if (a.hosting) details.push("IP属性：" + "🖥️ 机房IP");
  var lines = [""].concat(details);
  if (details.length) lines.push("");
  lines.push("IPPure系数：查询失败");
  finish(lines, "#3D90ED", "globe.asia.australia", nodeName);
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
  // IPPure 与 ip-api 并行：IPPure 给系数与 IP 属性，ip-api 给宽带/机构/移动标识
  return Promise.all([
    fetchJSON(IPPURE_URL, 5, node.policy).catch(function () { return null; }),
    fetchJSON(IPAPI_URL, 5, node.policy).catch(function () { return null; })
  ]).then(function (results) {
    var p = results[0];
    var a = results[1];
    // IPPure 返回了无 ip 字段的错误响应时，也视为失败，走 ip-api 兜底，避免面板半空
    if (p && p.ip) {
      renderIPPure(node.name, p, a);
    } else if (a && a.query) {
      renderIPApi(node.name, a);
    } else {
      fail(new Error("IPPure 与 ip-api 均查询失败"));
    }
  });
});
