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
 *   节点阻断检测 = title="🌐 节点阻断检测", content="点刷新开始检测", script-name=block_check, icon=bolt.horizontal.icloud.fill, icon-color=#467fcf
 *
 *   [Script]
 *   block_check = type=generic, script-path=block_check_surge.js, argument=group=Proxy&target=example.com:443
 *
 * 参数说明：
 *   group   要检测的 select 策略组名，脚本自动取该组当前选中的节点做"走节点"测试；
 *           不填则默认取第一个 select 组的当前选择。
 *   target  节点服务器地址 host:port。Surge 不向脚本开放节点的服务器地址（圈 X 版用
 *           get_server_description 读取，Surge 无此 API），只能手动填，仅用于
 *           check-host / Globalping 的远端探测；不填则跳过这两项。
 *
 * 使用：打开策略页面板区，点该面板的刷新按钮执行检测（全程约 10~20 秒）。
 */

const IP_API = "http://ip-api.com/json?lang=zh-CN";
const CHECK_HOST = "https://check-host.net";
const GP_API = "https://api.globalping.io/v1/measurements";
const TIMEOUT = 10; // Surge $httpClient 的 timeout 单位为秒

// ---------- 参数解析 ----------
function parseArgs() {
  var args = {};
  var raw = (typeof $argument !== "undefined") ? $argument : null;
  if (!raw) return args;
  if (typeof raw === "object") return raw;
  String(raw).split("&").forEach(function (pair) {
    var i = pair.indexOf("=");
    if (i > 0) {
      var k = decodeURIComponent(pair.substring(0, i));
      var v = decodeURIComponent(pair.substring(i + 1));
      args[k] = v;
    }
  });
  return args;
}

const ARGS = parseArgs();
const GROUP = ARGS.group || "";
const TARGET = ARGS.target || "";

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
  return {
    host: target.substring(0, colon),
    port: target.substring(colon + 1)
  };
}

// ---------- 主流程 ----------
function run() {
  var policy = getSelectedPolicy(GROUP);
  var tag = policy || "当前节点";
  var t = parseTarget(TARGET);
  startChecks(tag, policy, t.host, t.port);
}

function startChecks(tag, policy, host, port) {
  // A: 走节点访问 ip-api（policy 指定为当前选中节点；无节点时按当前出站）
  var nodeOpts = { url: IP_API };
  if (policy) nodeOpts.policy = policy;
  var pA = http(nodeOpts)
    .then(function (body) { return { src: "node", ok: true, data: JSON.parse(body) }; })
    .catch(function () { return { src: "node", ok: false }; });

  // B: 本机直连访问 ip-api（不带 policy 即直连）
  var pB = http({ url: IP_API })
    .then(function (body) { return { src: "direct", ok: true, data: JSON.parse(body) }; })
    .catch(function () { return { src: "direct", ok: false }; });

  // C: check-host 远端 TCP 探测
  var pC;
  if (host && port) {
    var target = host + ":" + port;
    var checkUrl = CHECK_HOST + "/check-tcp?host=" + encodeURIComponent(target) + "&max_nodes=10";
    pC = http({ url: checkUrl, headers: { "Accept": "application/json" } })
      .then(function (body) {
        var d = JSON.parse(body);
        if (!d.ok || !d.request_id) return { src: "remote", ok: false, error: "提交失败" };
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
                if (nr && Array.isArray(nr) && nr.length > 0 && nr[0].time !== undefined) {
                  reachable = true;
                  ms = formatMs(nr[0].time * 1000);
                }
                items.push({ flag: flag, ms: ms });
              });
              return { src: "remote", ok: reachable, data: items };
            })
            .catch(function () { return { src: "remote", ok: false, error: "查询失败" }; });
        });
      })
      .catch(function () { return { src: "remote", ok: false, error: "请求失败" }; });
  } else {
    pC = Promise.resolve({ src: "remote", ok: false, error: "未配置 target 地址" });
  }

  Promise.allSettled([pA, pB, pC]).then(function (results) {
    var node = results[0].value;
    var direct = results[1].value;
    var checkHost = results[2].value;

    var nOk = node && node.ok;
    var dOk = direct && direct.ok;
    var cOk = checkHost && checkHost.ok;

    // check-host 通 + 节点不通 → 触发国内定位
    if (dOk && cOk && !nOk && host && port) {
      runGlobalping(tag, host, port, node, direct, checkHost);
    } else {
      render(tag, node, direct, checkHost, null);
    }
  });
}

function runGlobalping(tag, host, port, node, direct, checkHost) {
  var body = {
    type: "ping",
    target: host,
    measurementOptions: { port: parseInt(port), protocol: "TCP" },
    locations: [{ country: "CN", tags: ["eyeball-network"] }],
    limit: 12
  };

  http({
    url: GP_API,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (respBody) {
    var d = JSON.parse(respBody);
    if (!d.id) { render(tag, node, direct, checkHost, null); return; }

    sleep(6000).then(function () {
      http({ url: GP_API + "/" + d.id, headers: { "Accept": "application/json" } })
        .then(function (respBody2) {
          render(tag, node, direct, checkHost, JSON.parse(respBody2));
        })
        .catch(function () { render(tag, node, direct, checkHost, null); });
    });
  }).catch(function () { render(tag, node, direct, checkHost, null); });
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

  var conclusion;
  if (reachableIsps.length === 0) {
    conclusion = "🚫 GFW 全局阻断 — 国内三大运营商均无法访问";
  } else if (blockedIsps.length > 0) {
    conclusion = "🚫 运营商级拦截 — " + blockedIsps.join("、") + " 不可达，" + reachableIsps.join("、") + " 正常";
  } else {
    conclusion = "✅ 国内三大运营商全部可达，非 GFW 或运营商拦截，请检查客户端配置";
  }

  return { ispGroups: ispGroups, conclusion: conclusion };
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

function getFlag(cc) {
  if (!cc || cc.length !== 2) return "🌍";
  var cp = cc.toUpperCase().split('').map(function (c) { return 127397 + c.charCodeAt(); });
  return String.fromCodePoint.apply(null, cp);
}

// ---------- 渲染（Surge 面板为纯文本，无 HTML） ----------
function render(tag, node, direct, remote, gpData) {
  var nOk = node && node.ok;
  var dOk = direct && direct.ok;
  var rOk = remote && remote.ok;

  var lines = [];

  // 节点代理
  lines.push("节点代理: " + (nOk ? "✅ 正常" : "❌ 不可达"));
  if (nOk && node.data) {
    var d = node.data;
    lines.push("IP: " + d.query);
    lines.push("位置: " + [d.country, d.regionName, d.city].filter(Boolean).join(" - "));
    lines.push("ISP: " + (d.isp || "未知"));
  }

  // 本机网络
  lines.push("本机网络: " + (dOk ? "✅ 正常" : "❌ 异常"));

  // 远端探测
  lines.push("远端探测: " + (rOk ? "✅ 可达" : "❌ 不可达"));
  if (remote && remote.data && remote.data.length > 0) {
    var items = remote.data;
    for (var i = 0; i < items.length; i += 2) {
      var line = items[i].flag + " " + items[i].ms;
      if (i + 1 < items.length) line += "    " + items[i + 1].flag + " " + items[i + 1].ms;
      lines.push(line);
    }
  } else if (remote && remote.error) {
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
      lines.push("国内探测: " + (domesticReachable ? "✅ 可达" : "❌ 不可达"));
      for (var i2 = 0; i2 < allProbes.length; i2 += 2) {
        var l2 = (allProbes[i2].ok ? "✅" : "❌") + allProbes[i2].label + " " + allProbes[i2].ms;
        if (i2 + 1 < allProbes.length) {
          l2 += "    " + (allProbes[i2 + 1].ok ? "✅" : "❌") + allProbes[i2 + 1].label + " " + allProbes[i2 + 1].ms;
        }
        lines.push(l2);
      }
    }
  }

  // 诊断结论
  lines.push("📋 诊断结论");
  if (!dOk) {
    lines.push("⚠️ 本机网络异常");
  } else if (nOk && rOk) {
    lines.push("✅ 节点正常");
  } else if (!nOk && rOk && dOk) {
    if (gpData && gpData.results) {
      var a2 = analyzeBlockSource(gpData);
      lines.push(a2 && a2.conclusion ? a2.conclusion : "🚫 疑似被运营商/GFW 阻断");
    } else {
      lines.push("🚫 疑似被运营商/GFW 阻断");
    }
  } else if (!nOk && !rOk && dOk) {
    lines.push("💤 节点离线");
  } else {
    lines.push("❓ 数据不完整");
  }

  lines.push("节点: " + (tag || "当前节点"));

  $done({
    title: "🌐 节点阻断检测",
    content: lines.join("\n"),
    icon: "bolt.horizontal.icloud.fill",
    "icon-color": "#467fcf"
  });
}

try {
  run();
} catch (e) {
  $done({
    title: "🌐 节点阻断检测",
    content: "🛑 脚本异常: " + (e && e.message ? e.message : e),
    icon: "bolt.horizontal.icloud.fill",
    "icon-color": "#f44336"
  });
}
