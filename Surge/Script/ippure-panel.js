// Net.Coffee 节点信息面板 (Surge)
// 数据来源：https://ip.net.coffee/ip/（信任评分标准：0-100，分越高越可信；与 IPPure 系数方向相反）
// 接口（2026-11-23 实测，站方前端 JS 内确认）：
//   1. 出口 IP：ip-api.com（带 policy 走节点）取 query，失败时回落 api.ipify.org
//   2. 主查询：GET https://ip.net.coffee/api/ip/lookup/<IP>（JSON，含 trust_score、ASN、地理、原生性、风险信号）
//   3. 人机流量：GET https://ip.net.coffee/api/ipv2/radar/<ASN>（JSON {ok,human,bot}，近 28 天；仅 IPv4，失败时不显示该行）
// 显示（2026-11-23 用户定版 v4）：位置中文（国家 · 城市）、评分（89%纯净）+ ▦ 条（10 格，分数/10 四舍五入）、分段空行、IP 属性（✅ 原生 / 🌐 广播+注册国）、标记（缩进子项，⚠️ 机房 IP 等）、运营商类型、人机流量（分两行，第二行缩进对齐）、场景评估（首行 + 全角空格缩进对齐）、服务商（去法律后缀）、ASN（带“ASN：”标签 + 全名，>32 超宽时回落 asname 短码，截图证实 35 宽会断行）（不显示 IP；每行控制在 32 字宽内防换行）
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
  PE: "秘鲁", VE: "委内瑞拉", NZ: "新西兰", IS: "冰岛", LU: "卢森堡",
  CN: "中国", PA: "巴拿马", SC: "塞舌尔", BZ: "伯利兹", KY: "开曼群岛",
  VG: "英属维尔京群岛", BM: "百慕大", MU: "毛里求斯", KZ: "哈萨克斯坦",
  UZ: "乌兹别克斯坦", KG: "吉尔吉斯斯坦", AF: "阿富汗", IR: "伊朗",
  KP: "朝鲜", SY: "叙利亚", CU: "古巴", BY: "白俄罗斯", TM: "土库曼斯坦",
  MM: "缅甸", JO: "约旦", SO: "索马里", SN: "塞内加尔", MO: "澳门",
  MN: "蒙古", LA: "老挝", KH: "柬埔寨", BD: "孟加拉国", PK: "巴基斯坦",
  LK: "斯里兰卡", NP: "尼泊尔", GE: "格鲁吉亚", AM: "亚美尼亚",
  AZ: "阿塞拜疆", MD: "摩尔多瓦", RS: "塞尔维亚", HR: "克罗地亚",
  SI: "斯洛文尼亚", SK: "斯洛伐克", BG: "保加利亚", GR: "希腊",
  CY: "塞浦路斯", MT: "马耳他", DZ: "阿尔及利亚", MA: "摩洛哥",
  TN: "突尼斯", GH: "加纳", CI: "科特迪瓦"
};

function countryZh(cc, fallbackEn) {
  if (!cc) return fallbackEn || "";
  var zh = COUNTRY_ZH[cc.toUpperCase()];
  return zh || fallbackEn || cc;
}

// 常用城市中文名（位置行用中文；不在表里时用接口英文名）
var CITY_ZH = {
  "New York": "纽约", "Los Angeles": "洛杉矶", "San Francisco": "旧金山",
  "San Jose": "圣何塞", "Seattle": "西雅图", "Chicago": "芝加哥",
  "Dallas": "达拉斯", "Houston": "休斯顿", "Miami": "迈阿密",
  "Atlanta": "亚特兰大", "Ashburn": "阿什本", "Denver": "丹佛",
  "Phoenix": "菲尼克斯", "Las Vegas": "拉斯维加斯", "Boston": "波士顿",
  "Washington": "华盛顿", "Portland": "波特兰", "San Diego": "圣迭戈",
  "Tokyo": "东京", "Osaka": "大阪", "Singapore": "新加坡",
  "Hong Kong": "香港", "London": "伦敦", "Frankfurt": "法兰克福",
  "Amsterdam": "阿姆斯特丹", "Paris": "巴黎", "Madrid": "马德里",
  "Milan": "米兰", "Stockholm": "斯德哥尔摩", "Sydney": "悉尼",
  "Melbourne": "墨尔本", "Seoul": "首尔", "Taipei": "台北",
  "Toronto": "多伦多", "Montreal": "蒙特利尔", "Vancouver": "温哥华",
  "Mumbai": "孟买", "Bangkok": "曼谷", "Kuala Lumpur": "吉隆坡",
  "Jakarta": "雅加达", "Manila": "马尼拉", "Dubai": "迪拜",
  "Johannesburg": "约翰内斯堡",
  "Mountain View": "山景城", "Beijing": "北京", "Shanghai": "上海",
  "Guangzhou": "广州", "Shenzhen": "深圳", "Chengdu": "成都",
  "Hangzhou": "杭州", "Wuhan": "武汉", "Xi'an": "西安",
  "Chongqing": "重庆", "Nanjing": "南京", "Tianjin": "天津",
  "Suzhou": "苏州", "Harbin": "哈尔滨", "Shenyang": "沈阳",
  "Dalian": "大连", "Qingdao": "青岛", "Xiamen": "厦门",
  "Fuzhou": "福州", "Changsha": "长沙", "Zhengzhou": "郑州",
  "Kunming": "昆明", "Hefei": "合肥", "Ningbo": "宁波", "Wuxi": "无锡",
  // 州/省（无城市时 pickGeo 用省回落）
  "California": "加利福尼亚", "Texas": "得克萨斯", "Florida": "佛罗里达",
  "Virginia": "弗吉尼亚", "Oregon": "俄勒冈", "Illinois": "伊利诺伊",
  "Georgia": "佐治亚", "New Jersey": "新泽西", "Ohio": "俄亥俄"
};

function cityZh(en) {
  if (!en) return "";
  return CITY_ZH[en] || en;
}

// 显示宽度：CJK/全角/emoji/几何图形算 2，拉丁/数字/半角标点算 1（用于 ASN 行超宽回落判断）
function dispWidth(s) {
  if (typeof s !== "string") return 0;
  var w = 0;
  for (var i = 0; i < s.length; i++) {
    var c = s.codePointAt(i);
    if (c > 0xFFFF) i++;
    if (c === 0xFE0F || c === 0x200D) continue; // 变体选择符 / 零宽连接符不占宽
    if ((c >= 0x1100 && c <= 0x115F) || (c >= 0x2E80 && c <= 0x9FFF) ||
        (c >= 0xA000 && c <= 0xA4CF) || (c >= 0xAC00 && c <= 0xD7A3) ||
        (c >= 0xF900 && c <= 0xFAFF) || (c >= 0xFE30 && c <= 0xFE4F) ||
        (c >= 0xFF00 && c <= 0xFF60) || (c >= 0xFFE0 && c <= 0xFFE6) ||
        (c >= 0x1F000 && c <= 0x1FAFF) || (c >= 0x20000 && c <= 0x2FFFF) ||
        c === 0x3000 || (c >= 0x2500 && c <= 0x25FF)) w += 2;
    else w += 1;
  }
  return w;
}

// 标记行的 emoji：机房 ⚠️、住宅 🏠、移动 📱、任播 🌐、爬虫 🤖、公共服务 ℹ️
function tagEmojiFor(tag) {
  if (tag === "机房 IP") return "⚠️";
  if (tag === "住宅 IP") return "🏠";
  if (tag === "移动网络") return "📱";
  if (tag === "任播 DNS") return "🌐";
  if (tag === "爬虫/机器人") return "🤖";
  if (tag === "公共服务") return "ℹ️";
  if (tag === "Bogon") return "⚠️";
  return "";
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

// 位置：用接口主字段（与站方头部一致）；只取国家 + 城市（无城市时用省），省市同时出现时只留城市，防换行
function pickGeo(d) {
  return { country: d.country || "", region: "", city: d.city || d.region || "" };
}

// 运营商名去法律后缀防换行：Cogent Communications, LLC → Cogent Communications（仅服务商行用）
function cleanOrg(name) {
  if (typeof name !== "string") return name;
  return name.replace(/,?\s*(LLC|Inc|Corp|Ltd|Limited|Company|Co\.?\s*Ltd\.?|Co\.?)\.?$/i, "").trim();
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
  if (d.isResidential) return "住宅 IP";
  if (d.is_datacenter) return "机房 IP";
  if (d.is_bogon) return "Bogon";
  return "";
}

// 用户定版 v4（2026-11-23 08:11）：分段空行；IP 属性用 ✅（原生）/ 🌐（广播）；标记为缩进子项；人机分两行；场景双空格；ASN 带标签
function renderNetCoffee(nodeName, d, radar) {
  var isV6 = String(d.ip || "").indexOf(":") !== -1;
  var score = Number(d.trust_score);
  var tier = tierOf(score);
  var geo = pickGeo(d);
  // 续行缩进：全角空格 ×5（“场景评估：”/“人机流量：”的宽度，续行对齐到值下方）
  var INDENT = "　".repeat(5);
  var sections = [];

  // 第一段：位置 / 评分 / ▦ 条
  var head = [];
  var locCountry = countryZh(d.countryCode, d.country);
  var locCity = cityZh(geo.city);
  var loc = locCountry;
  if (locCity) loc += " · " + locCity;
  if (loc) head.push(loc);
  if (isFinite(score)) {
    head.push("评分：" + score + "%" + tier.tag);
    var filled = Math.round(score / 10);
    if (filled < 0) filled = 0;
    if (filled > 10) filled = 10;
    head.push("▦".repeat(filled) + "□".repeat(10 - filled));
  } else {
    head.push("评分：查询失败");
  }
  if (head.length) sections.push(head);

  // 第二段：IP 属性 + 标记（标记为缩进子项）
  var ipSec = [];
  var cc = (d.countryCode || "").toUpperCase();
  var reg = (d.registered_country_code || "").toUpperCase();
  if (cc && reg) {
    if (cc === reg) {
      ipSec.push("IP 属性：✅ " + countryZh(cc, d.country) + " · 原生 IP");
    } else {
      ipSec.push("IP 属性：🌐 " + countryZh(reg, d.registered_country) + " · 广播 IP");
    }
  } else if (cc) {
    ipSec.push("IP 属性：✅ " + countryZh(cc, d.country));
  }
  var tag = ipTag(d);
  if (tag) {
    var te = tagEmojiFor(tag);
    ipSec.push(INDENT + "标记：" + (te ? te + " " : "") + tag);
  }
  if (ipSec.length) sections.push(ipSec);

  // 第三段：运营商类型 + 人机流量（分两行，第二行缩进对齐）
  var netSec = [];
  if (d.company_type) {
    var ct = String(d.company_type).toLowerCase();
    var ctLabel = { cdn: "CDN", isp: "ISP", hosting: "Hosting", business: "Business",
      education: "Education", government: "Government", military: "Military" }[ct];
    if (!ctLabel) ctLabel = ct.charAt(0).toUpperCase() + ct.slice(1);
    netSec.push("运营商类型：" + ctLabel);
  }
  if (!isV6 && radar && radar.ok && typeof radar.human === "number" && typeof radar.bot === "number") {
    var h = Math.round(radar.human * 10) / 10;
    var b = Math.round(radar.bot * 10) / 10;
    netSec.push("人机流量：人类 " + h + "%");
    netSec.push(INDENT + "机器 " + b + "%");
  }
  if (netSec.length) sections.push(netSec);

  // 第四段：场景评估（公共服务 IP 不评估；IPv6 不评估）
  var sceneSec = [];
  if (isV6) {
    sceneSec.push("场景评估：IPv6 地址暂不评估");
  } else if (!d.is_public_service) {
    var sc = sceneScores(d);
    if (sc) {
      sceneSec.push("场景评估：TikTok " + sc.tiktok.score + " " + sc.tiktok.verdict);
      sceneSec.push(INDENT + "社媒运营 " + sc.social.score + " " + sc.social.verdict);
      sceneSec.push(INDENT + "AI应用 " + sc.ai.score + " " + sc.ai.verdict);
    }
  }
  if (sceneSec.length) sections.push(sceneSec);

  // 第五段：服务商 + ASN
  var asnSec = [];
  var provider = cleanOrg(d.isp || d.company_name || d.asOrganization || d.datacenter_name || "");
  if (provider) asnSec.push("服务商：" + provider);
  // ASN：带“ASN：”标签 + 全名；超宽（>32，截图证实 35 宽会断行）时回落到 asname 短码，再超宽只留 AS 号
  if (d.asn) {
    var org = cleanOrg(d.asOrganization || "");
    var asnLine = "ASN：AS" + d.asn + (org ? " – " + org : "");
    if (dispWidth(asnLine) > 32 && d.asname) {
      asnLine = "ASN：AS" + d.asn + " – " + d.asname;
    }
    if (dispWidth(asnLine) > 32) asnLine = "ASN：AS" + d.asn;
    asnSec.push(asnLine);
  }
  if (asnSec.length) sections.push(asnSec);

  // 组装：各段之间空一行
  var lines = [];
  sections.forEach(function (sec, idx) {
    if (idx > 0) lines.push("");
    lines = lines.concat(sec);
  });

  var icon;
  var color = tier.color;
  if (isFinite(score) && score < 25) {
    icon = "exclamationmark.octagon.fill";
  } else if (isFinite(score) && score < 50) {
    icon = "exclamationmark.triangle.fill";
  } else {
    icon = "house.fill";
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
