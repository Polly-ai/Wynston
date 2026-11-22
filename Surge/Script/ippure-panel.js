// Net.Coffee 节点信息面板 (Surge)
// 数据来源：https://ip.net.coffee/ip/（信任评分标准：0-100，分越高越可信；与 IPPure 系数方向相反）
// 接口（2026-11-23 实测，站方前端 JS 内确认）：
//   1. 出口 IP：ip-api.com（带 policy 走节点）取 query，失败时回落 api.ipify.org
//   2. 主查询：GET https://ip.net.coffee/api/ip/lookup/<IP>（JSON，含 trust_score、ASN、地理、原生性、风险信号）
//   3. 人机流量：GET https://ip.net.coffee/api/ipv2/radar/<ASN>（JSON {ok,human,bot}，近 28 天；仅 IPv4，失败时不显示该行）
// 显示（按 ip.net.coffee/ip/ 页面版式，文字版）：位置、评分、IP 原生性、标记、运营商类型、人机流量、场景评估、服务商、ASN（不显示 IP）
// 评分档位（站方 tierOf）：≥95 极度纯净，≥80 纯净，≥50 良好，≥25 中性，<25 可疑
// 场景评估（站方 v2 sceneScores 原样复刻）：基础分 roundHalfUp(trust/10)；原生 +0.5、非机房真人 +0.5、business -0.5、机房 -2、广播 -1、非 AI 机房再 -1、代理/VPN/Tor（AI -2、其它 -3）、历史滥用（AI -0.5、其它 -1）、滥用分/蜜罐扣分、爬虫 -0.5；0-10 clamp，有风险信号最高 9；地区 block/partial 按站方 REGION 表；IPv6 不评估，公共服务 IP 不评估
//
// 节点名选中逻辑（沿用旧版）：
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

var IPAPI_URL = "http://ip-api.com/json/?fields=status,query";
var IPIFY_URL = "https://api.ipify.org?format=json";
var LOOKUP_URL = "https://ip.net.coffee/api/ip/lookup/";
var RADAR_URL = "https://ip.net.coffee/api/ipv2/radar/";

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
      if (resp && resp.status && resp.status !== 200) return reject(new Error("HTTP " + resp.status));
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

// 评分档位（站方 tierOf）
function tierOf(score) {
  if (!isFinite(score)) return { tag: "-", color: "#3D90ED" };
  if (score >= 95) return { tag: "极度纯净", color: "#34C759" };
  if (score >= 80) return { tag: "纯净", color: "#34C759" };
  if (score >= 50) return { tag: "良好", color: "#3D90ED" };
  if (score >= 25) return { tag: "中性", color: "#FFCC00" };
  return { tag: "可疑", color: "#FF3B30" };
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

// 国家代码 → 国旗 emoji（地区指示符）
function flagEmoji(cc) {
  if (!cc || cc.length !== 2) return "";
  try {
    var a = cc.toUpperCase();
    return String.fromCodePoint(127397 + a.charCodeAt(0), 127397 + a.charCodeAt(1));
  } catch (e) {
    return "";
  }
}

// 常用国家中文名（面板原生性行用中文，其余行沿用接口英文地名）
var COUNTRY_ZH = {
  US: "美国", JP: "日本", HK: "香港", TW: "台湾", SG: "新加坡", KR: "韩国",
  GB: "英国", DE: "德国", NL: "荷兰", FR: "法国", CA: "加拿大", AU: "澳大利亚",
  IN: "印度", BR: "巴西", RU: "俄罗斯", TR: "土耳其", ID: "印度尼西亚",
  MY: "马来西亚", TH: "泰国", VN: "越南", PH: "菲律宾", IT: "意大利",
  ES: "西班牙", SE: "瑞典", NO: "挪威", FI: "芬兰", DK: "丹麦", PL: "波兰",
  CH: "瑞士", AT: "奥地利", BE: "比利时", IE: "爱尔兰", PT: "葡萄牙",
  CZ: "捷克", HU: "匈牙利", RO: "罗马尼亚", UA: "乌克兰", IL: "以色列",
  AE: "阿联酋", SA: "沙特阿拉伯", EG: "埃及", ZA: "南非", NG: "尼日利亚",
  KE: "肯尼亚", MX: "墨西哥", AR: "阿根廷", CL: "智利", CO: "哥伦比亚",
  PE: "秘鲁", VE: "委内瑞拉", NZ: "新西兰", IS: "冰岛", LU: "卢森堡"
};

function countryZh(cc, fallbackEn) {
  if (!cc) return fallbackEn || "";
  var zh = COUNTRY_ZH[cc.toUpperCase()];
  return zh || fallbackEn || cc;
}

function roundHalfUp(x) { return Math.floor(x + 0.5); }

// 场景评估地区表（站方 v2 REGION）
var REGION = {
  tiktok: { block: ["CN", "HK", "IN", "IR", "AF", "KP", "JO", "SO", "SN", "KG", "UZ"], partial: [] },
  social: { block: ["CN", "IR", "KP", "TM"], partial: ["RU", "MM"] },
  ai: { block: ["CN", "RU", "BY", "IR", "KP", "CU", "SY", "AF"], partial: ["HK", "MO", "VE", "MM"] }
};

// 场景评估（站方 v2 sceneScores 原样复刻；返回 {tiktok,social,ai}，每项 {score,blocked,verdict}）
function sceneScores(d) {
  var trust = Number(d.trust_score);
  if (!isFinite(trust)) return null;
  var base = roundHalfUp(trust / 10);
  var cc = (d.countryCode || "").toUpperCase();
  var reg = (d.registered_country_code || "").toUpperCase();
  var dc = !!(d.is_datacenter || d.company_type === "hosting" || d.asn_kind === "hosting" || d.asn_kind === "cdn");
  var native = !!(cc && reg && cc === reg);
  var broadcast = !!(cc && reg && cc !== reg);
  var human = !dc && !d.is_crawler && !d.is_public_service;
  var business = (d.company_type || "") === "business";
  var pv = !!(d.is_proxy || d.is_vpn || d.is_tor);
  var intel = d.intelligence || {};
  var threats = !!d.is_abuser;
  var abRaw = parseFloat(intel.abuser_score_raw != null ? intel.abuser_score_raw : d.abuser_score);
  var abPen = 0;
  if (isFinite(abRaw)) {
    abPen = abRaw > 0.05 ? 2 : abRaw > 0.025 ? 1 : abRaw > 0.01 ? 0.5 : 0;
  } else {
    var lv = String(intel.abuser_level || "").toLowerCase();
    abPen = (lv === "high" || lv === "very_high" || lv === "veryhigh") ? 2 : lv === "elevated" ? 1 : 0;
  }
  var hpRaw = (intel.rep_threat != null && intel.rep_threat !== "") ? intel.rep_threat : intel.httpbl_threat;
  var hp = Number(hpRaw);
  var hpPen = (isFinite(hp) && hp > 0) ? (hp <= 25 ? 1 : 2) : 0;
  var crawler = !!d.is_crawler;
  var risky = threats || abPen > 0 || hpPen > 0 || crawler || pv;

  function calc(kind) {
    var s = base;
    if (native) s += 0.5;
    if (human) s += 0.5;
    if (business) s -= 0.5;
    if (dc) s -= 2;
    if (broadcast) s -= 1;
    if (kind !== "ai" && dc) s -= 1;
    if (pv) s -= (kind === "ai" ? 2 : 3);
    if (threats) s -= (kind === "ai" ? 0.5 : 1);
    s -= abPen;
    s -= hpPen;
    if (crawler) s -= 0.5;
    s = roundHalfUp(s);
    if (s < 0) s = 0;
    if (s > 10) s = 10;
    if (risky && s > 9) s = 9;
    var r = REGION[kind];
    var blocked = r.block.indexOf(cc) >= 0;
    var partial = r.partial.indexOf(cc) >= 0;
    if (blocked) return { score: 0, blocked: true, verdict: "地区不可用" };
    if (partial && s > 5) s = 5;
    var v;
    if (partial) v = "部分可用";
    else if (s >= 10) v = "极佳";
    else if (s >= 8) v = "推荐";
    else if (s >= 5) v = (kind === "ai" ? "可以尝试" : "可用");
    else v = "不推荐";
    return { score: s, blocked: false, verdict: v };
  }
  return { tiktok: calc("tiktok"), social: calc("social"), ai: calc("ai") };
}

// 位置：用接口主字段（与站方头部一致；主字段无省/市时只显示国家）
function pickGeo(d) {
  return { country: d.country || "", region: d.region || "", city: d.city || "" };
}

// 标记：爬虫 / 公共服务 / 移动 / 住宅 / 机房 / Bogon
function ipTag(d) {
  if (d.is_crawler) return "爬虫/机器人";
  if (d.is_public_service) {
    if (d.public_service && d.public_service.service_type === "anycast_dns") return "任播 DNS";
    if (d.ai_verdict && d.ai_verdict.label) return d.ai_verdict.label;
    return "公共服务";
  }
  if (d.is_mobile) return "移动网络";
  if (d.isResidential) return "住宅IP";
  if (d.is_datacenter) return "机房IP";
  if (d.is_bogon) return "Bogon";
  return "";
}

function renderNetCoffee(nodeName, d, radar) {
  var isV6 = String(d.ip || "").indexOf(":") !== -1;
  var score = Number(d.trust_score);
  var tier = tierOf(score);
  var geo = pickGeo(d);
  var flag = flagEmoji(d.countryCode);
  var lines = [];

  // 顶部：位置
  var loc = buildLocation(geo.country, geo.region, geo.city);
  if (loc) lines.push((flag ? flag + " " : "") + loc);
  // 评分（0 高危 – 100 可信，分越高越可信）
  if (isFinite(score)) {
    lines.push("评分：" + score + " " + tier.tag + "（0 高危 – 100 可信）");
  } else {
    lines.push("评分：查询失败");
  }
  lines.push("");
  lines.push("使用场景 / 类型");

  // IP 原生性：注册国与归属国一致为原生，否则广播
  var cc = (d.countryCode || "").toUpperCase();
  var reg = (d.registered_country_code || "").toUpperCase();
  if (cc && reg) {
    if (cc === reg) {
      lines.push("IP 原生性：" + (flag ? flag + " " : "") + countryZh(cc, d.country) + " · 原生 IP");
    } else {
      lines.push("IP 原生性：" + (flag ? flag + " " : "") + countryZh(cc, d.country) + " · 广播 IP（注册：" + countryZh(reg, d.registered_country) + "）");
    }
  } else if (cc) {
    lines.push("IP 原生性：" + (flag ? flag + " " : "") + countryZh(cc, d.country));
  }

  var tag = ipTag(d);
  if (tag) lines.push("标记：" + tag);

  if (d.company_type) {
    var ct = d.company_type;
    lines.push("运营商类型：" + ct.charAt(0).toUpperCase() + ct.slice(1));
  }

  // 人机流量（radar 按 ASN，近 28 天；IPv6 没有）
  if (!isV6 && radar && radar.ok && typeof radar.human === "number" && typeof radar.bot === "number") {
    var h = Math.round(radar.human * 10) / 10;
    var b = Math.round(radar.bot * 10) / 10;
    var lean = h >= b ? "人类偏多" : "机器偏多";
    lines.push("人机流量：人类 " + h + "% · 机器 " + b + "%（" + lean + "）");
  }

  // 场景评估（IPv6 不评估，公共服务 IP 不评估）
  if (isV6) {
    lines.push("场景评估：IPv6 地址暂不评估");
  } else if (!d.is_public_service) {
    var sc = sceneScores(d);
    if (sc) {
      lines.push("场景评估：TikTok " + sc.tiktok.score + " " + sc.tiktok.verdict +
        " · 社媒运营 " + sc.social.score + " " + sc.social.verdict +
        " · AI应用 " + sc.ai.score + " " + sc.ai.verdict);
    }
  }

  // 服务商（站方字段优先级：isp → company_name → asOrganization → datacenter_name；显示站方原值）
  var provider = d.isp || d.company_name || d.asOrganization || d.datacenter_name || "";
  if (provider) lines.push("服务商：" + provider);

  var asnOrg = d.asOrganization || d.asname || "";
  if (d.asn) {
    lines.push("ASN：AS" + d.asn + (asnOrg ? " – " + asnOrg : ""));
  }

  // 图标：分数走风险色；高分按 IP 属性适配
  var icon;
  var color = tier.color;
  if (isFinite(score) && score < 25) {
    icon = "exclamationmark.octagon.fill";
  } else if (isFinite(score) && score < 50) {
    icon = "exclamationmark.triangle.fill";
  } else {
    icon = "globe.asia.australia";
    if (d.isResidential) icon = "house.fill";
    else if (d.is_datacenter) icon = "server.rack";
  }

  finish(lines, color, icon, nodeName);
}

// 取出口 IP：先 ip-api，失败回落 ipify
function getEgressIP(policy) {
  return fetchJSON(IPAPI_URL, 5, policy).then(function (a) {
    if (a && a.status === "success" && a.query) return a.query;
    throw new Error("ip-api 无结果");
  }).catch(function () {
    return fetchJSON(IPIFY_URL, 5, policy).then(function (j) {
      if (j && j.ip) return j.ip;
      throw new Error("无法获取出口 IP");
    });
  });
}

var manualNode = getArg("node");
var groupArg = getArg("group");
var bareName = (typeof $argument === "string" && $argument && $argument.indexOf("=") === -1) ? $argument : "";
var targetGroup = groupArg || bareName || "Proxy";

var nodeTask = manualNode
  ? Promise.resolve({ name: manualNode, policy: manualNode })
  : resolveNode(targetGroup);

nodeTask.then(function (node) {
  // 先解析节点，再带 policy 强制走该节点查出口 IP，然后用该 IP 查 net.coffee
  return getEgressIP(node.policy).then(function (egressIP) {
    return fetchJSON(LOOKUP_URL + encodeURIComponent(egressIP), 8, node.policy).then(function (d) {
      if (!d || !d.ip || typeof d.trust_score === "undefined") throw new Error("net.coffee 查询失败");
      var radarTask = Promise.resolve(null);
      if (d.asn && String(egressIP).indexOf(":") === -1) {
        radarTask = fetchJSON(RADAR_URL + encodeURIComponent(d.asn), 8, node.policy).catch(function () { return null; });
      }
      return radarTask.then(function (radar) {
        renderNetCoffee(node.name, d, radar);
      });
    });
  });
}).catch(function (e) { fail(e); });
