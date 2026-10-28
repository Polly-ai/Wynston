// 路由追踪（Surge 面板脚本 v5）
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
// v4.1：仍显示未知的跳（国家未知、ASN 也不在补丁表里），再调一次 ip-api
// 按 IP 查国家与运营商（走节点，并行查，20 秒没查完就先用已有结果渲染）。
// 路径尽量完整显示：每段标注跳号范围（如 中国电信 AS4134（3-4）），
// 段与段之间的无响应跳也点名（如 第 4 跳无响应），不再只给总数。
// 路径竖排显示：每段一行、箭头引导，一眼看清去程怎么走，
// 同时保留跳号范围与无响应跳点名（完整与一目了然兼顾）。
// 对齐：路径标题单独一行，之后每段统一用“  → ”开头，标签左边缘严格对齐。
//
// v5：路径主标签改成地理位置（itdog 表格风格）：局域网 / 中国/广东/中山/电信 /
// 骨干网/电信 / 中国/电信CN2 / 美国/洛杉矶/Cogent；每跳 ip-api 查省市运营商，
// 骨干网段按知名 IP 段直接定性，查不到才回退到国家/运营商/未知。
//
// v5.1：内网跳只认开头的局域网，途中出现的内网地址显示为 --（跟 itdog 的 --
// 行一致，不再乱标局域网）；运营商兜底只认单字名，多字匹配不到关键词的宁可
// 不写（避免把 "Zhejiang Aiyun ..." 错写成浙江）；补桂林等城市中文名。
//
// v5.2：监测点与国内路径城市一律不显示拼音（没录入的城市直接省略城市名，
// 监测点则显示国内电信）；追踪改 TCP 优先（443 端口，防火墙挡 ICMP 时 often
// 能多看到几跳），TCP 到不了终点自动回落 ICMP；每次取 2 条探针结果，挑响应
// 跳最多的那条显示（有的探针路径全程不响应，换一条就有）。
//
// 数据来源：Globalping 公开免费接口（免 key，纯 REST：POST 建任务 + 轮询取结果）。
// 监测点首选陕西电信（西安 4134），不在线时依次退到国内电信、国内任意探针；
// 监测点那行永远显示实际用的探针。社区探针上下线频繁，陕西电信探针不在线
// 时面板会用其他探针顶上并如实标注，不是偷偷换。
var LOCATIONS_CHAIN = [
  [{ country: 'CN', city: "Xi'an", asn: 4134, limit: 2 }],
  [{ country: 'CN', asn: 4134, limit: 2 }],
  [{ country: 'CN', limit: 2 }],
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
  // 国内城市（ip-api 英文 -> 中文；查不到的城市原样显示英文）
  Zhongshan: '中山', Shantou: '汕头', Xiamen: '厦门', Fuzhou: '福州',
  Guilin: '桂林', Liuzhou: '柳州',
  Suzhou: '苏州', Wuxi: '无锡', Ningbo: '宁波', Wenzhou: '温州',
  Hefei: '合肥', Jinan: '济南', Qingdao: '青岛', Shenyang: '沈阳',
  Dalian: '大连', Changchun: '长春', Harbin: '哈尔滨', Tianjin: '天津',
  Chongqing: '重庆', Taiyuan: '太原', Shijiazhuang: '石家庄',
  Kunming: '昆明', Guiyang: '贵阳', Haikou: '海口', Sanya: '三亚',
  Xining: '西宁', Lanzhou: '兰州', Yinchuan: '银川', Urumqi: '乌鲁木齐',
  Lhasa: '拉萨', Hohhot: '呼和浩特', Nanchang: '南昌',
  // 广东全部地级市（探针常落广东；其余省份补主要地级市）
  Dongguan: '东莞', Foshan: '佛山', Zhuhai: '珠海', Huizhou: '惠州',
  Jiangmen: '江门', Zhanjiang: '湛江', Maoming: '茂名', Zhaoqing: '肇庆',
  Jieyang: '揭阳', Chaozhou: '潮州', Meizhou: '梅州', Shanwei: '汕尾',
  Heyuan: '河源', Yangjiang: '阳江', Qingyuan: '清远', Yunfu: '云浮',
  Shaoguan: '韶关',
  // 华北
  Tangshan: '唐山', Baoding: '保定', Handan: '邯郸', Qinhuangdao: '秦皇岛',
  Cangzhou: '沧州', Langfang: '廊坊', Xingtai: '邢台', Zhangjiakou: '张家口',
  Chengde: '承德', Hengshui: '衡水', Datong: '大同', Yuncheng: '运城',
  Linfen: '临汾', Yangquan: '阳泉', Jinzhong: '晋中', Jincheng: '晋城',
  Changzhi: '长治', Shuozhou: '朔州', Xinzhou: '忻州', Luliang: '吕梁',
  Baotou: '包头', Ordos: '鄂尔多斯', Chifeng: '赤峰', Tongliao: '通辽',
  Hulunbuir: '呼伦贝尔', Bayannur: '巴彦淖尔', Ulanqab: '乌兰察布',
  Xilingol: '锡林郭勒', Wuhai: '乌海',
  // 东北
  Anshan: '鞍山', Fushun: '抚顺', Jinzhou: '锦州', Dandong: '丹东',
  Yingkou: '营口', Fuxin: '阜新', Liaoyang: '辽阳', Panjin: '盘锦',
  Tieling: '铁岭', Chaoyang: '朝阳', Huludao: '葫芦岛', Benxi: '本溪',
  Jilin: '吉林', Siping: '四平', Liaoyuan: '辽源', Tonghua: '通化',
  Baishan: '白山', Songyuan: '松原', Baicheng: '白城', Yanji: '延吉',
  Qiqihar: '齐齐哈尔', Mudanjiang: '牡丹江', Jiamusi: '佳木斯', Daqing: '大庆',
  Jixi: '鸡西', Hegang: '鹤岗', Shuangyashan: '双鸭山', Qitaihe: '七台河',
  Heihe: '黑河', Suihua: '绥化',
  // 华东
  Changzhou: '常州', Nantong: '南通', Yancheng: '盐城', Yangzhou: '扬州',
  Zhenjiang: '镇江', Xuzhou: '徐州', Lianyungang: '连云港', Huaian: '淮安',
  Suqian: '宿迁', Jiaxing: '嘉兴', Huzhou: '湖州', Shaoxing: '绍兴',
  Jinhua: '金华', Quzhou: '衢州', Zhoushan: '舟山', Lishui: '丽水',
  Quanzhou: '泉州', Zhangzhou: '漳州', Putian: '莆田', Sanming: '三明',
  Longyan: '龙岩', Ningde: '宁德', Nanping: '南平',
  Zibo: '淄博', Yantai: '烟台', Weifang: '潍坊', Jining: '济宁',
  Taian: '泰安', Weihai: '威海', Rizhao: '日照', Linyi: '临沂',
  Dezhou: '德州', Liaocheng: '聊城', Binzhou: '滨州', Heze: '菏泽',
  Wuhu: '芜湖', Maanshan: '马鞍山', Anqing: '安庆', Fuyang: '阜阳',
  Bengbu: '蚌埠', Chuzhou: '滁州', Xuancheng: '宣城', Huangshan: '黄山',
  Chizhou: '池州', Bozhou: '亳州', Liuan: '六安', Huaibei: '淮北',
  Tongling: '铜陵', Ganzhou: '赣州', Jiujiang: '九江', Shangrao: '上饶',
  "Ji'an": '吉安', Jingdezhen: '景德镇', Pingxiang: '萍乡', Xinyu: '新余',
  Yingtan: '鹰潭',
  // 华中
  Luoyang: '洛阳', Kaifeng: '开封', Anyang: '安阳', Xinxiang: '新乡',
  Jiaozuo: '焦作', Xuchang: '许昌', Luohe: '漯河', Sanmenxia: '三门峡',
  Nanyang: '南阳', Shangqiu: '商丘', Xinyang: '信阳', Zhoukou: '周口',
  Zhumadian: '驻马店', Pingdingshan: '平顶山', Hebi: '鹤壁', Puyang: '濮阳',
  Xiangyang: '襄阳', Yichang: '宜昌', Jingzhou: '荆州', Shiyan: '十堰',
  Huangshi: '黄石', Xiaogan: '孝感', Huanggang: '黄冈', Xianning: '咸宁',
  Suizhou: '随州', Enshi: '恩施', Ezhou: '鄂州',
  Zhuzhou: '株洲', Xiangtan: '湘潭', Hengyang: '衡阳', Shaoyang: '邵阳',
  Yueyang: '岳阳', Changde: '常德', Zhangjiajie: '张家界', Yiyang: '益阳',
  Chenzhou: '郴州', Yongzhou: '永州', Huaihua: '怀化', Loudi: '娄底',
  // 西南、西北
  Mianyang: '绵阳', Deyang: '德阳', Yibin: '宜宾', Nanchong: '南充',
  Dazhou: '达州', Luzhou: '泸州', Zigong: '自贡', Panzhihua: '攀枝花',
  Leshan: '乐山', Neijiang: '内江', Suining: '遂宁', Guangan: '广安',
  Meishan: '眉山', Yaan: '雅安', Bazhong: '巴中', Ziyang: '资阳',
  Zunyi: '遵义', Anshun: '安顺', Bijie: '毕节', Tongren: '铜仁',
  Liupanshui: '六盘水', Yuxi: '玉溪', Qujing: '曲靖', Baoshan: '保山',
  Zhaotong: '昭通', Lijiang: '丽江', Puer: '普洱', Lincang: '临沧',
  Dali: '大理', Chuxiong: '楚雄', Honghe: '红河', Wenshan: '文山',
  Xishuangbanna: '西双版纳', Xianyang: '咸阳', Baoji: '宝鸡', Weinan: '渭南',
  Yanan: '延安', Hanzhong: '汉中', Ankang: '安康', Shangluo: '商洛',
  Tongchuan: '铜川', Tianshui: '天水', Baiyin: '白银', Pingliang: '平凉',
  Jiuquan: '酒泉', Jiayuguan: '嘉峪关', Wuwei: '武威', Zhangye: '张掖',
  Qingyang: '庆阳', Dingxi: '定西', Longnan: '陇南', Linxia: '临夏',
  Shizuishan: '石嘴山', Wuzhong: '吴忠', Guyuan: '固原', Zhongwei: '中卫',
  Haidong: '海东', Haibei: '海北', Huangnan: '黄南', Guoluo: '果洛',
  Yushu: '玉树', Haixi: '海西', Karamay: '克拉玛依', Turpan: '吐鲁番',
  Hami: '哈密', Changji: '昌吉', Aksu: '阿克苏', Kashgar: '喀什',
  Hotan: '和田', Ili: '伊犁', Tacheng: '塔城', Altay: '阿勒泰',
  Shihezi: '石河子', Bortala: '博尔塔拉', Bayingolin: '巴音郭楞',
  Kizilsu: '克孜勒苏', Shigatse: '日喀则', Qamdo: '昌都', Shannan: '山南',
  Nyingchi: '林芝', Nagqu: '那曲', Ngari: '阿里',
  // 广西、海南、港澳（南宁、桂林、柳州已在上文）
  Wuzhou: '梧州', Beihai: '北海', Fangchenggang: '防城港', Qinzhou: '钦州',
  Guigang: '贵港', Hezhou: '贺州', Baise: '百色', Hechi: '河池',
  Laibin: '来宾', Chongzuo: '崇左', Qionghai: '琼海', Danzhou: '儋州',
  Wanning: '万宁', Wenchang: '文昌', Dongfang: '东方', Macau: '澳门',
};
var REGION_NAMES = {
  Guangdong: '广东', Zhejiang: '浙江', Jiangsu: '江苏', Fujian: '福建',
  Shandong: '山东', Henan: '河南', Hubei: '湖北', Hunan: '湖南',
  Sichuan: '四川', Shaanxi: '陕西', Liaoning: '辽宁', Jilin: '吉林',
  Heilongjiang: '黑龙江', Hebei: '河北', Shanxi: '山西', Anhui: '安徽',
  Jiangxi: '江西', Guizhou: '贵州', Yunnan: '云南', Gansu: '甘肃',
  Qinghai: '青海', Ningxia: '宁夏', Xinjiang: '新疆', Tibet: '西藏',
  'Inner Mongolia': '内蒙古', Guangxi: '广西', Hainan: '海南',
  Beijing: '北京', Tianjin: '天津', Shanghai: '上海', Chongqing: '重庆',
  'Hong Kong': '香港', Taiwan: '台湾', Macau: '澳门',
};

// 工作方式：
// 1. 当前节点（选中策略组决定，拿不到时读全局出站策略）
// 2. 经该节点查出口 IP（ip-api），这个 IP 就是追踪目标（VPS 节点出口即服务器 IP）
// 3. Globalping 从国内探针追踪该 IP，取 hops
// 4. 每跳先定骨干网段（202.97/59.43/219.158），再用 ip-api 查省/市/运营商；
//    查不到回退到 geoip 国家 + ipasn ASN；连续相同标签合并成一段，带跳号范围；
//    终点国家之外的途经国家 = 绕路
// IP 显示按惯例只留前两段。

var IP_API = 'http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,isp,org,as,query';
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
  219498: 'TRIFONOV',
};
// 知名骨干网段（itdog 同款定性）：202.97 电信骨干、59.43 电信 CN2、219.158 联通骨干
function backboneOf(ip) {
  if (!ip) return null;
  if (ip.indexOf('202.97.') === 0) return { label: '骨干网/电信', asn: '4134' };
  if (ip.indexOf('59.43.') === 0) return { label: '中国/电信CN2', asn: '4134' };
  if (ip.indexOf('219.158.') === 0) return { label: '骨干网/联通', asn: '4837' };
  return null;
}
function ispShort(isp) {
  if (!isp) return '';
  var s = isp.toUpperCase();
  if (s.indexOf('TELECOM') !== -1 || s.indexOf('CHINANET') !== -1) return '电信';
  if (s.indexOf('UNICOM') !== -1) return '联通';
  if (s.indexOf('MOBILE') !== -1) return '移动';
  if (s.indexOf('COGENT') !== -1) return 'Cogent';
  if (s.indexOf('HURRICANE') !== -1) return 'HE';
  if (s.indexOf('RETN') !== -1) return 'RETN';
  if (s.indexOf('TELIA') !== -1) return 'Telia';
  if (s.indexOf('LUMEN') !== -1 || s.indexOf('LEVEL 3') !== -1) return 'Lumen';
  if (s.indexOf('PCCW') !== -1) return 'PCCW';
  if (s.indexOf('NTT') !== -1) return 'NTT';
  if (s.indexOf('CLOUDFLARE') !== -1) return 'Cloudflare';
  if (s.indexOf('GOOGLE') !== -1) return 'Google';
  if (s.indexOf('AMAZON') !== -1) return 'AWS';
  if (s.indexOf('MICROSOFT') !== -1) return 'Azure';
  if (s.indexOf('ALIBABA') !== -1) return '阿里云';
  if (s.indexOf('TENCENT') !== -1) return '腾讯云';
  if (s.indexOf('HUAWEI') !== -1) return '华为云';
  if (s.indexOf('AIYUN') !== -1) return 'Aiyun';
  // 兜底：单字运营商直接用；多字又匹配不到关键词的，宁可不写运营商，也别写错
  // （比如 "Zhejiang Aiyun ..." 取首字会错写成浙江）
  var w = isp.split(/[\s,]+/);
  return (w.length === 1) ? w[0] : '';
}
// ip-api 结果 -> 地理位置标签（itdog 风格，斜杠分隔；国内带省，国外不带州）
function geoLabel(j) {
  var country = COUNTRY_NAMES[j.countryCode] || j.country || '';
  var parts = [];
  function pushPart(x) {
    if (x && (parts.length === 0 || parts[parts.length - 1] !== x)) parts.push(x);
  }
  pushPart(country);
  if (country === '中国') pushPart(REGION_NAMES[j.regionName] || j.regionName || '');
  // 国内城市没录入的直接省略城市名（不显示拼音）；国外城市本来就是英文名，保留
  pushPart(country === '中国' ? (CITY_NAMES[j.city] || '') : (CITY_NAMES[j.city] || j.city || ''));
  pushPart(ispShort(j.isp || j.org));
  return { label: parts.join('/'), country: country || null };
}

function maskIP(ip) {
  if (!ip) return '未知';
  var v4 = ip.split('.');
  if (v4.length === 4) return v4[0] + '.' + v4[1] + '.x.x';
  var v6 = ip.split(':');
  if (v6.length > 2) return v6[0] + ':' + v6[1] + '::xxxx';
  return ip;
}

// 多条探针结果里挑最好的：先看是否到终点，再看响应跳数
function pickBest(results, target) {
  var best = null;
  var bestScore = -1;
  for (var i = 0; i < results.length; i++) {
    var r = results[i];
    if (!r || !r.result || !r.result.hops) continue;
    var hops = r.result.hops;
    var n = 0;
    var reached = false;
    for (var j = 0; j < hops.length; j++) {
      if (hops[j].resolvedAddress) {
        n++;
        if (hops[j].resolvedAddress === target) reached = true;
      }
    }
    var score = n + (reached ? 1000 : 0);
    if (score > bestScore) {
      bestScore = score;
      best = r;
    }
  }
  return best;
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
    var egress = { loc: '', asn: '', countryCn: '', geo: '' };
    try {
      var j = JSON.parse(data);
      if (j && j.status === 'success') {
        target = j.query;
        egress.countryCn = COUNTRY_NAMES[j.countryCode] || j.country || '';
        var cityCn = CITY_NAMES[j.city] || j.city || '';
        egress.loc = [egress.countryCn, cityCn].filter(function (x) { return !!x; }).join(' ');
        egress.asn = (j.as || '').split(' ')[0];
        egress.geo = geoLabel(j).label;
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
    var ctx = { displayName: displayName, egressLine: egressLine, egress: egress, target: target, policy: policy, proto: 'TCP', retried: false };
    var apiReachable = false;
    function tryCreate(i) {
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
          measurementOptions: ctx.proto === 'TCP' ? { protocol: 'TCP', port: 443 } : { protocol: 'ICMP' },
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
    }
    // TCP 到不了终点时回落 ICMP 再跑一次（终点防火墙可能挡 TCP）
    ctx.retryWithICMP = function () {
      if (ctx.retried) return;
      ctx.retried = true;
      ctx.proto = 'ICMP';
      tryCreate(0);
    };
    tryCreate(0);
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
      if (status === 'finished' && r.results && r.results.length > 0) {
        var best = pickBest(r.results, ctx.target);
        if (best && best.result) {
          var reached = false;
          var bhops = best.result.hops || [];
          for (var bi = 0; bi < bhops.length; bi++) {
            if (bhops[bi].resolvedAddress === ctx.target) { reached = true; break; }
          }
          if (!reached && ctx.proto === 'TCP' && !ctx.retried && ctx.retryWithICMP) {
            ctx.retryWithICMP();
            return;
          }
          render(best, ctx);
          return;
        }
      }
      if (status === 'failed') {
        if (ctx.proto === 'TCP' && !ctx.retried && ctx.retryWithICMP) {
          ctx.retryWithICMP();
          return;
        }
        finish(['节点：' + ctx.displayName, ctx.egressLine, '路径：探针追踪失败']);
        return;
      }
      setTimeout(function () { poll(id, attempt + 1, ctx); }, POLL_INTERVAL);
    });
  }

  function render(first, ctx) {
    var probe = first.probe || {};
    var hops = (first.result && first.result.hops) || [];
    var monitor = (CITY_NAMES[probe.city] || '国内') + (carrierOf(probe.network) || '');
    // 第一遍：每跳的基础信息。地理位置优先用 ip-api（省/市/运营商），
    // 本地 geoip/asn 只作 ip-api 查不到时的后备；骨干网直接定标签；
    // 内网跳只认开头的局域网（探针自己的内网），途中出现的内网地址标为 --
    var hopInfos = [];
    var lastIdx = 0;
    var seenPublic = false;
    for (var i = 0; i < hops.length; i++) {
      var h = hops[i];
      var ip = h.resolvedAddress;
      if (!ip) continue;
      lastIdx = i + 1;
      var isTarget = (ip === ctx.target);
      var priv = isPrivateIP(ip);
      var privLabel = priv ? (seenPublic ? '--' : '局域网') : null;
      if (!priv) seenPublic = true;
      var bb = priv ? null : backboneOf(ip);
      var c = null;
      var asn = null;
      var geo = null;
      var geoCountry = null;
      if (bb) {
        geo = bb.label;
        geoCountry = '中国';
        asn = bb.asn;
      } else if (isTarget && ctx.egress.geo) {
        geo = ctx.egress.geo;
        geoCountry = ctx.egress.countryCn;
      } else if (!priv) {
        c = countryOf(ip, h.resolvedHostname);
        if (isTarget && ctx.egress.countryCn) c = ctx.egress.countryCn;
        asn = asnOf(ip);
      }
      var rtt = null;
      if (isTarget && h.timings && h.timings.length > 0 && h.timings[0].rtt !== undefined) {
        rtt = Math.round(h.timings[0].rtt);
      }
      hopInfos.push({ ip: ip, idx: i + 1, priv: priv, privLabel: privLabel, country: c, asn: asn, geo: geo, geoCountry: geoCountry, isTarget: isTarget, rtt: rtt, org: null });
    }
    // 需要查 ip-api 的跳：公网、非骨干、非终点（终点直接用出口查询的结果）
    var toQuery = [];
    for (var k = 0; k < hopInfos.length; k++) {
      var hi = hopInfos[k];
      if (!hi.priv && !hi.geo) toQuery.push(hi);
    }
    var rendered = false;
    function doRender() {
      if (rendered) return;
      rendered = true;
      // 第二遍：分段。标签优先地理位置（局域网/--/骨干网/ip-api 省市运营商），
      // 查不到才回退到国家/运营商/未知；连续相同标签合并成一段，带跳号范围。
      var segs = [];
      var reached = false;
      var finalRTT = null;
      var lastCountry = null;
      for (var i = 0; i < hopInfos.length; i++) {
        var hi = hopInfos[i];
        var c = hi.geoCountry || hi.country;
        var asn = hi.asn;
        var label = null;
        if (hi.priv) {
          label = hi.privLabel;
          c = null;
        } else if (hi.geo) {
          label = hi.geo;
        } else {
          var prev = segs.length > 0 ? segs[segs.length - 1] : null;
          if (!c && asn && prev && prev.asn === asn && prev.country) c = prev.country;
          if (c) {
            label = c;
            if (asn) label += 'AS' + asn;
          } else if (asn && ASN_ORG[asn]) {
            label = ASN_ORG[asn] + ' AS' + asn;
          } else if (hi.org) {
            label = hi.org;
            if (asn) label += ' AS' + asn;
          } else {
            label = '未知';
            if (asn) label += 'AS' + asn;
          }
        }
        if (segs.length === 0 || segs[segs.length - 1].label !== label) {
          segs.push({ label: label, country: c, asn: asn, firstIdx: hi.idx, lastIdx: hi.idx, count: 1 });
        } else {
          var cur = segs[segs.length - 1];
          cur.lastIdx = hi.idx;
          cur.count++;
        }
        lastCountry = c || lastCountry;
        if (hi.isTarget) {
          reached = true;
          if (hi.rtt !== null) finalRTT = hi.rtt;
        }
      }
      var hopCount = hopInfos.length;
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
      // 未响应的跳（第一跳与最后一跳之间、没有返回 IP 的位置）
      var gaps = [];
      if (hopInfos.length > 0) {
        var seen = {};
        for (var gi = 0; gi < hopInfos.length; gi++) seen[hopInfos[gi].idx] = true;
        var rawHops = (first.result && first.result.hops) || [];
        for (var g = hopInfos[0].idx; g <= hopInfos[hopInfos.length - 1].idx; g++) {
          if (!seen[g] && rawHops[g - 1] && !rawHops[g - 1].resolvedAddress) gaps.push(g);
        }
      }
      // 路径竖排对齐：标题单独一行，之后每段统一用“  → ”开头，
      // 标签左边缘严格对齐；无响应跳单独一行点名
      lines.push('路径（' + hopCount + ' 跳）：');
      for (var pi = 0; pi < segs.length; pi++) {
        var s = segs[pi];
        var range = (s.count === 1) ? s.firstIdx : (s.firstIdx + '-' + s.lastIdx);
        lines.push('  → ' + s.label + '（' + range + '）');
      }
      if (gaps.length > 0) lines.push('  ✕ 第 ' + gaps.join('、') + ' 跳无响应');
      if (reached) {
        var land = '落地：' + maskIP(ctx.target) + ' | ' + (ctx.egress.loc || '') + (ctx.egress.asn ? ' ' + ctx.egress.asn : '') + (finalRTT !== null ? ' | ' + finalRTT + 'ms' : '');
        lines.push(land);
        var dest = segs[segs.length - 1].country;
        var transit = [];
        for (var t = 0; t < segs.length; t++) {
          var cc = segs[t].country;
          if (cc && cc !== '中国' && cc !== dest && transit.indexOf(cc) === -1) transit.push(cc);
        }
        lines.push(transit.length > 0 ? '结论：⚠️ 绕路（经' + transit.join('、') + '）' : '结论：✅ 直连，无绕路');
      } else {
        lines.push('落地：未到达（最后响应第 ' + lastIdx + ' 跳 · ' + (lastCountry || '未知') + '）');
        lines.push('结论：⏳ 追踪未到终点，结论仅供参考');
      }
      finish(lines);
    }
    if (toQuery.length === 0) {
      doRender();
      return;
    }
    // 查 ip-api 拿每跳的省/市/运营商（走节点，并行查，20 秒没查完先用已有结果渲染）
    var done = 0;
    setTimeout(function () { doRender(); }, 20000);
    toQuery.forEach(function (hi) {
      $httpClient.get({ url: 'http://ip-api.com/json/' + hi.ip + '?fields=status,country,countryCode,regionName,city,isp,org,as', policy: ctx.policy, timeout: 8 }, function (error, response, data) {
        try {
          var j = JSON.parse(data);
          if (j && j.status === 'success') {
            var gl = geoLabel(j);
            if (gl.label) {
              hi.geo = gl.label;
              hi.geoCountry = gl.country;
            } else if (j.as) {
              var m = j.as.match(/^AS\d+\s+(.+)$/);
              if (m) hi.org = m[1];
            }
          }
        } catch (e) {}
        done++;
        if (done >= toQuery.length) doRender();
      });
    });
  }
});
