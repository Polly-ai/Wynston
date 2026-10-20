/**
 * 节点连通性检测脚本（Surge Panel 版）
 * 原作：https://github.com/RavelloH （Quantumult X 版）
 * 本版：移植到 Surge 信息面板，检测逻辑与结论判定与原版一致
 *
 * 功能：
 *   检测指定策略组当前选中的节点是否可连接，并判断是否被运营商/GFW 阻断
 *
 * 配置 (Surge):
 *   [Panel]
 *   节点阻断检测 = title="节点阻断检测", content="点刷新开始检测", script-name=block_check, icon=network, icon-color=#467fcf
 *
 *   [Script]
 *   block_check = type=generic, script-path=block_check_surge.js, argument=Proxy
 *
 * 参数说明（两种写法等效）：
 *   group=策略组名：实时读取该组当前选中节点（默认 Proxy）
 *   纯名字，如 argument=Proxy：等同于 group=Proxy
 *   远端探测默认自动进行：Surge 不开放节点服务器地址（圈 X 版用
 *           get_server_description 读取，Surge 无此 API），故脚本缓存每次成功测得的
 *           出口 IP 作为探测目标——节点正常时用本次出口 IP，节点异常时用上次缓存，
 *           以 Ping 方式做 check-host / Globalping 探测。如需精确到端口的 TCP 探测，
 *           可手动指定 argument=Proxy&target=example.com:443（手动 target 优先）。
 *
 * 使用：在策略页的面板上点刷新按钮执行（不要在脚本列表里直接运行，generic 脚本
 *       手动运行时 $done 结果不显示）。全程约 5~20 秒，25 秒未完成会强制出结果。
 */

const IP_API = "http://ip-api.com/json?lang=zh-CN";
const CHECK_HOST = "https://check-host.net";
const GP_API = "https://api.globalping.io/v1/measurements";
const TIMEOUT = 6; // Surge $httpClient 的 timeout 单位为秒

// ---------- 参数解析 ----------
function parseArgs() {
  var raw = (typeof $argument !== "undefined") ? $argument : null;
  if (!raw) return { group: "", target: "" };
  if (typeof raw === "object") {
    return { group: raw.group || "", target: raw.target || "" };
  }
  var s = String(raw).trim();
  if (s.indexOf("=") === -1) return { group: s, target: "" }; // argument=Proxy 这种简写
  var args = { group: "", target: "" };
  s.split("&").forEach(function (pair) {
    var i = pair.indexOf("=");
    if (i > 0) {
      var k = decodeURIComponent(pair.substring(0, i));
      var v = decodeURIComponent(pair.substring(i + 1));
      if (k === "group" || k === "target") args[k] = v;
    }
  });
  return args;
}

const ARGS = parseArgs();
const GROUP = ARGS.group;
const TARGET = ARGS.target;

// ---------- 工具 ----------
function http(options) {
  return new Promise(function (resolve, reject) {
    var method = (options.method || "GET").toLowerCase();
    var opts = {
      url: options.url,
      headers: options.headers || {},
      timeout: TIMEOUT
    };
    if (options.policy) opts.policy = options.policy;
    if (options.body !== undefined) opts.body = options.body;
    $httpClient[method](opts, function (error, response, data) {
      if (error) reject(error);
      else resolve(data);
    });
  });
}

function sleep(ms) {
  return new Promise(function (resolve) { setTimeout(resolve, ms); });
}

function getSelectedPolicy(group) {
  try {
    var details = $surge.selectGroupDetails();
    if (!details || !details.decisions) return null;
    if (group && details.decisions[group]) return details.decisions[group];
    var keys = Object.keys(details.decisions);
    return keys.length ? details.decisions[keys[0]] : null;
  } catch (e) {
    return null;
  }
}

function parseTarget(target) {
  if (!target) return { host: null, port: null };
  var colon = target.lastIndexOf(":");
  if (colon === -1) return { host: null, port: null };
  return { host: target.substring(0, colon), port: target.substring(colon + 1) };
}

// ---------- 出口 IP 缓存（远端探测自动取目标用） ----------
function exitCacheKey(policy) { return "block_check_exit_" + (policy || "default"); }

function readCachedExit(policy) {
  try {
    if (typeof $persistentStore === "undefined") return null;
    var v = $persistentStore.read(exitCacheKey(policy));
    return v ? String(v) : null;
  } catch (e) { return null; }
}

function writeCachedExit(policy, ip) {
  try {
    if (typeof $persistentStore === "undefined" || !ip) return;
    $persistentStore.write(String(ip), exitCacheKey(policy));
  } catch (e) {}
}

// ---------- 全局状态（供看门狗强制出结果） ----------
var STATE = { node: null, direct: null, remote: null, gp: null, tag: "" };
var RENDERED = false;

// ---------- 主流程 ----------
function run() {
  var policy = getSelectedPolicy(GROUP || "Proxy");
  console.log("[block_check] group=" + (GROUP || "Proxy") + ", 当前节点=" + policy);
  STATE.tag = policy || "当前节点";
  var t = parseTarget(TARGET);

  // 25 秒看门狗：无论卡在哪一步，都强制渲染当前已有结果
  setTimeout(function () {
    if (!RENDERED) render(STATE.tag, STATE.node, STATE.direct, STATE.remote, STATE.gp, true);
  }, 25000);

  startChecks(STATE.tag, policy, t.host, t.port);
}

function startChecks(tag, policy, host, port) {
  // A: 走节点访问 ip-api（policy 指定为当前选中节点；无节点时按当前出站）
  var nodeOpts = { url: IP_API };
  if (policy) nodeOpts.policy = policy;
  var pA = http(nodeOpts)
    .then(function (body) {
      var data = JSON.parse(body);
      writeCachedExit(policy, data.query);
      return { src: "node", ok: true, data: data };
    })
    .catch(function () { return { src: "node", ok: false }; });

  // B: 本机直连访问 ip-api（不带 policy 即直连）
  var pB = http({ url: IP_API })
    .then(function (body) { return { src: "direct", ok: true, data: JSON.parse(body) }; })
    .catch(function () { return { src: "direct", ok: false }; });

  // C: check-host 远端探测。等节点测试出结果再定探测目标：
  //    手动 target → TCP 精确探测；否则用出口 IP（本次的优先，其次上次缓存）做 Ping 探测
  var pC = pA.then(function (aRes) {
    var probeHost = host, probePort = port, probeTcp = !!(host && port);
    if (!probeHost) {
      var ip = (aRes && aRes.ok && aRes.data && aRes.data.query) ? aRes.data.query : readCachedExit(policy);
      if (ip) { probeHost = ip; probePort = null; probeTcp = false; }
    }
    if (!probeHost) {
      return { src: "remote", ok: false, error: "无出口 IP 记录，跳过远端探测" };
    }
    var checkTarget = probeTcp ? (probeHost + ":" + probePort) : probeHost;
    var checkUrl = CHECK_HOST + (probeTcp ? "/check-tcp?host=" : "/check-ping?host=") + encodeURIComponent(checkTarget) + "&max_nodes=10";
    return http({ url: checkUrl, headers: { "Accept": "application/json" } })
      .then(function (body) {
        var d = JSON.parse(body);
        if (!d.ok || !d.request_id) return { src: "remote", ok: false, error: "提交失败", probeHost: probeHost, probePort: probePort };
        var rid = d.request_id;
        var nodeList = d.nodes || {};
        var nodeNames = Object.keys(nodeList);
        var countryMap = {};
        nodeNames.forEach(function (n) {
          var info = nodeList[n];
          if (info && info.length >= 1) countryMap[n] = info[0];
        });
        return sleep(3500).then(function () {
          return http({ url: CHECK_HOST + "/check-result/" + rid, headers: { "Accept": "application/json" } })
            .then(function (body2) {
              var res = JSON.parse(body2);
              var reachable = false;
              var items = [];
              nodeNames.forEach(function (n) {
                var cc = countryMap[n] || "";
                var flag = cc ? getFlag(cc) : "🌍";
                var nr = res[n];
                var ms = "--.--ms";
                if (nr && Array.isArray(nr)) {
                  for (var e = 0; e < nr.length; e++) {
                    if (nr[e] && typeof nr[e].time === "number") {
                      reachable = true;
                      ms = formatMs(nr[e].time * 1000);
                      break;
                    }
                  }
                }
                items.push({ flag: flag, ms: ms });
              });
              return { src: "remote", ok: reachable, data: items, probeHost: probeHost, probePort: probePort };
            })
            .catch(function () { return { src: "remote", ok: false, error: "查询失败", probeHost: probeHost, probePort: probePort }; });
        });
      })
      .catch(function () { return { src: "remote", ok: false, error: "请求失败", probeHost: probeHost, probePort: probePort }; });
  });

  pA.then(function (r) { STATE.node = r; });
  pB.then(function (r) { STATE.direct = r; });
  pC.then(function (r) { STATE.remote = r; });

  Promise.allSettled([pA, pB, pC]).then(function (results) {
    console.log("[block_check] 三路检测完成: " + results.map(function (r) { return r.status + "/" + (r.value ? (r.value.src + ":" + r.value.ok) : "?"); }).join(", "));
    var node = results[0].value;
    var direct = results[1].value;
    var checkHost = results[2].value;
    STATE.node = node; STATE.direct = direct; STATE.remote = checkHost;

    var nOk = node && node.ok;
    var dOk = direct && direct.ok;
    var cOk = checkHost && checkHost.ok;

    // check-host 通 + 节点不通 → 触发国内定位
    if (dOk && cOk && !nOk && checkHost.probeHost) {
      runGlobalping(tag, checkHost.probeHost, checkHost.probePort, node, direct, checkHost);
    } else {
      render(tag, node, direct, checkHost, null, false);
    }
  });
}

function runGlobalping(tag, host, port, node, direct, checkHost) {
  var body = {
    type: "ping",
    target: host,
    locations: [{ country: "CN", tags: ["eyeball-network"] }],
    limit: 12
  };
  if (port) body.measurementOptions = { port: parseInt(port), protocol: "TCP" };

  http({
    url: GP_API,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (respBody) {
    var d = JSON.parse(respBody);
    if (!d.id) { render(tag, node, direct, checkHost, null, false); return; }

    sleep(6000).then(function () {
      http({ url: GP_API + "/" + d.id, headers: { "Accept": "application/json" } })
        .then(function (respBody2) {
          var gp = JSON.parse(respBody2);
          STATE.gp = gp;
          render(tag, node, direct, checkHost, gp, false);
        })
        .catch(function () { render(tag, node, direct, checkHost, null, false); });
    });
  }).catch(function () { render(tag, node, direct, checkHost, null, false); });
}

// ---------- 分析 ----------
function classifyISP(network) {
  var n = network.toLowerCase();
  if (n.indexOf("unicom") !== -1 || n.indexOf("china unicom") !== -1) return "中国联通";
  if (n.indexOf("chinanet") !== -1 || n.indexOf("telecom") !== -1 || n.indexOf("china telecom") !== -1) return "中国电信";
  if (n.indexOf("mobile") !== -1 || n.indexOf("china mobile") !== -1) return "中国移动";
  return null;
}

function analyzeBlockSource(gpData) {
  var results = gpData.results;
  if (!results) return null;

  var ispGroups = {};
  for (var i = 0; i < results.length; i++) {
    var r = results[i];
    var isp = classifyISP(r.probe.network);
    if (!isp) continue;

    if (!ispGroups[isp]) ispGroups[isp] = { probes: [], reachable: false };

    var res = r.result;
    var ok = false;
    var ms = "--.--ms";
    var stats = res.stats;
    if (res.status === "finished" && stats) {
      ok = stats.rcv > 0;
      ms = ok ? formatMs(stats.avg || 0) : "--.--ms";
    }
    if (ok) ispGroups[isp].reachable = true;

    ispGroups[isp].probes.push({
      city: cnCity(r.probe.city),
      ok: ok,
      ms: ms
    });
  }

  var reachableIsps = [], blockedIsps = [];
  var keys = Object.keys(ispGroups);
  for (var k = 0; k < keys.length; k++) {
    var g = ispGroups[keys[k]];
    if (g.probes.length === 0) continue;
    if (g.reachable) reachableIsps.push(keys[k]); else blockedIsps.push(keys[k]);
  }

  var conclusion, kind;
  if (reachableIsps.length === 0) {
    conclusion = "GFW 全局阻断，国内三大运营商均无法访问";
    kind = "blocked";
  } else if (blockedIsps.length > 0) {
    conclusion = "运营商级拦截：" + blockedIsps.join("、") + " 不可达，" + reachableIsps.join("、") + " 正常";
    kind = "blocked";
  } else {
    conclusion = "国内三大运营商全部可达，非 GFW 或运营商拦截，请检查客户端配置";
    kind = "clear";
  }

  return { ispGroups: ispGroups, conclusion: conclusion, kind: kind };
}

function cnCity(en) {
  var map = {
    "Beijing": "北京", "Shanghai": "上海", "Guangzhou": "广州",
    "Shenzhen": "深圳", "Chengdu": "成都", "Hangzhou": "杭州",
    "Wuhan": "武汉", "Nanjing": "南京", "Tianjin": "天津",
    "Xi'an": "西安", "Changsha": "长沙", "Zhengzhou": "郑州",
    "Jinan": "济南", "Qingdao": "青岛", "Dalian": "大连",
    "Xiamen": "厦门", "Fuzhou": "福州", "Kunming": "昆明",
    "Hefei": "合肥", "Ningbo": "宁波", "Suzhou": "苏州",
    "Wuxi": "无锡", "Changzhou": "常州", "Guilin": "桂林",
    "Nanning": "南宁", "Haikou": "海口", "Sanya": "三亚",
    "Guiyang": "贵阳", "Lanzhou": "兰州", "Urumqi": "乌市",
    "Hohhot": "呼市", "Harbin": "哈市", "Changchun": "长春",
    "Shenyang": "沈阳", "Shijiazhuang": "石市", "Taiyuan": "太原",
    "Xuzhou": "徐州", "Yancheng": "盐城", "Taishan": "台山",
    "Nanchang": "南昌", "Foshan": "佛山", "Dongguan": "东莞",
    "Zhuhai": "珠海", "Zhongshan": "中山", "Huizhou": "惠州"
  };
  return map[en] || en;
}

function formatMs(ms) {
  if (ms >= 10000) {
    return Math.floor(ms) + "ms";
  } else if (ms >= 1000) {
    return Math.floor(ms).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "ms";
  } else if (ms >= 100) {
    return ms.toFixed(1) + "ms";
  } else if (ms >= 10) {
    return ms.toFixed(2) + "ms";
  } else if (ms <= 0) {
    return "0.00ms";
  } else {
    return ms.toFixed(3) + "ms";
  }
}

// IP 打码：只显示前两段，其余用 * 替代（如 203.0.*.*）
function maskIP(ip) {
  if (!ip) return "未知";
  ip = String(ip);
  if (ip.indexOf(".") !== -1) {
    var parts = ip.split(".");
    if (parts.length === 4) return parts[0] + "." + parts[1] + ".*.*";
    return ip;
  }
  if (ip.indexOf(":") !== -1) {
    var segs = ip.split(":").filter(function (s) { return s !== ""; });
    if (segs.length >= 2) return segs[0] + ":" + segs[1] + ":*";
    return ip;
  }
  return ip;
}

function getFlag(cc) {
  if (!cc || cc.length !== 2) return "🌍";
  var cp = cc.toUpperCase().split('').map(function (c) { return 127397 + c.charCodeAt(); });
  return String.fromCodePoint.apply(null, cp);
}

// ---------- 渲染（Surge 面板为纯文本，无 HTML） ----------
function dot(ok, pending, skip) {
  if (pending || skip) return "⚪";
  return ok ? "🟢" : "🔴";
}

function render(tag, node, direct, remote, gpData, forced) {
  if (RENDERED) return;
  RENDERED = true;

  var nOk = node && node.ok;
  var dOk = direct && direct.ok;
  var rOk = remote && remote.ok;
  var remoteSkipped = !!(remote && remote.error && remote.error.indexOf("跳过") !== -1);

  var lines = [];

  if (forced) lines.push("检测超时，以下为已完成部分");

  // 节点代理
  lines.push(dot(nOk, !node) + " 节点代理 · " + (node ? (nOk ? "正常" : "不可达") : "未完成"));
  if (nOk && node.data) {
    var d = node.data;
    lines.push("IP：" + maskIP(d.query));
    lines.push("位置：" + [d.country, d.regionName, d.city].filter(Boolean).join(" - "));
    lines.push("ISP：" + (d.isp || "未知"));
  }
  lines.push("");

  // 本机网络
  lines.push(dot(dOk, !direct) + " 本机网络 · " + (direct ? (dOk ? "正常" : "异常") : "未完成"));

  // 远端探测（按原版样式：标题行 + 国旗延迟两列）
  var remoteStatus;
  if (!remote) remoteStatus = "未完成";
  else if (remoteSkipped) remoteStatus = "已跳过";
  else remoteStatus = rOk ? "✅ 可达" : "❌ 不可达";
  lines.push("远端探测：" + remoteStatus);
  if (remote && remote.data && remote.data.length > 0) {
    var items = remote.data;
    for (var i = 0; i < items.length; i += 2) {
      var line = items[i].flag + " " + items[i].ms;
      if (i + 1 < items.length) line += "    " + items[i + 1].flag + " " + items[i + 1].ms;
      lines.push(line);
    }
  } else if (remote && remote.error && !remoteSkipped) {
    lines.push(remote.error);
  }

  // 国内定位（仅在阻断嫌疑时有数据）
  if (gpData && gpData.results) {
    var analysis = analyzeBlockSource(gpData);
    if (analysis) {
      var ispOrder = ["中国电信", "中国联通", "中国移动"];
      var ispAbbr = { "中国电信": "电信", "中国联通": "联通", "中国移动": "移动" };
      var allProbes = [];
      for (var j = 0; j < ispOrder.length; j++) {
        var group = analysis.ispGroups[ispOrder[j]];
        if (!group) continue;
        for (var p = 0; p < group.probes.length; p++) {
          allProbes.push({
            label: ispAbbr[ispOrder[j]] + "·" + group.probes[p].city,
            ms: group.probes[p].ms,
            ok: group.probes[p].ok
          });
        }
      }
      var domesticReachable = allProbes.some(function (p) { return p.ok; });
      lines.push(dot(domesticReachable) + " 国内探测 · " + (domesticReachable ? "可达" : "不可达"));
      for (var i2 = 0; i2 < allProbes.length; i2 += 2) {
        var l2 = allProbes[i2].label + " " + (allProbes[i2].ok ? allProbes[i2].ms : "超时");
        if (i2 + 1 < allProbes.length) {
          l2 += "    " + allProbes[i2 + 1].label + " " + (allProbes[i2 + 1].ok ? allProbes[i2 + 1].ms : "超时");
        }
        lines.push(l2);
      }
    }
  }

  // 诊断结论
  lines.push("");
  var conclusion;
  if (forced || !node || !direct || !remote) {
    conclusion = "数据不完整";
  } else if (!dOk) {
    conclusion = "⚠️ 本机网络异常";
  } else if (nOk && rOk) {
    conclusion = "✅ 节点正常";
  } else if (nOk && remoteSkipped) {
    conclusion = "✅ 节点正常（远端探测已跳过）";
  } else if (nOk && !rOk) {
    conclusion = "✅ 节点正常（远端探测不可达）";
  } else if (!nOk && rOk && dOk) {
    if (gpData && gpData.results) {
      var a2 = analyzeBlockSource(gpData);
      if (a2 && a2.conclusion) {
        conclusion = (a2.kind === "clear" ? "✅ " : "🚫 ") + a2.conclusion;
      } else {
        conclusion = "🚫 疑似被运营商/GFW 阻断";
      }
    } else {
      conclusion = "🚫 疑似被运营商/GFW 阻断";
    }
  } else if (!nOk && !rOk && dOk) {
    conclusion = remoteSkipped ? "节点不可达，远端探测已跳过，无法判定原因" : "💤 节点离线";
  } else {
    conclusion = "数据不完整";
  }
  lines.push("结论：" + conclusion);
  lines.push("节点：" + (tag || "当前节点"));

  console.log("[block_check] 渲染完成, forced=" + !!forced);
  $done({
    title: "节点阻断检测",
    content: lines.join("\n"),
    icon: "network",
    "icon-color": "#467fcf"
  });
}

console.log("[block_check] 脚本启动, argument=" + JSON.stringify(typeof $argument !== "undefined" ? $argument : null));
try {
  run();
} catch (e) {
  console.log("[block_check] 同步异常: " + (e && e.message ? e.message : e));
  $done({
    title: "节点阻断检测",
    content: "脚本异常：" + (e && e.message ? e.message : e),
    icon: "network",
    "icon-color": "#f44336"
  });
}
