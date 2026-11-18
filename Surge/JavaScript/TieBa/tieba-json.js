// Generated jq-equivalent transformations from TieBaAds.conf.
try { let o = JSON.parse($response.body); let matched = false;
if (o !== null && (typeof o !== 'object' || Array.isArray(o))) throw Error('root type');
if (new RegExp("^https?:\\/\\/tieba(c)?\\.baidu\\.com\\/c\\/f\\/search\\/discover").test($request.url)) { if (o === null) o = {}; if (o.data == null) o.data = {}; if (typeof o.data !== "object" || Array.isArray(o.data)) throw Error("data type"); o.data.discover_list = []; matched = true; }
if (new RegExp("^https?:\\/\\/tieba(c)?\\.baidu\\.com\\/c\\/f\\/sidebar\\/home").test($request.url)) { for (const k of ["game_center", "tools", "vip_banner", "task_list"]) if (o != null) delete o[k]; matched = true; }
if (new RegExp("^https?:\\/\\/tieba(c)?\\.baidu\\.com\\/c\\/u\\/user\\/profile").test($request.url)) { for (const k of ["duxiaoman", "namoaixud", "namoaixud_entry", "recom_naws_list", "duxiaoman_entry", "vip_banner"]) delete o[k]; if (!Array.isArray(o.zone_info) && (o.zone_info === null || typeof o.zone_info !== "object")) throw Error("zone_info type"); o.zone_info = Object.values(o.zone_info).filter(x => { if (x === null) return false; if (typeof x !== "object" || Array.isArray(x)) throw Error("zone item type"); return x.type === "common_func" || x.type === "auxiliary_func"; }); matched = true; }
if (new RegExp("^https?:\\/\\/tieba(c)?\\.baidu\\.com\\/c\\/f\\/forum\\/forumGuide").test($request.url)) { if (o === null) o = {}; o.hot_search = []; matched = true; }
if (new RegExp("^https?:\\/\\/tieba(c)?\\.baidu\\.com\\/mo\\/q\\/search\\/startPage").test($request.url)) { if (o != null) delete o.data; matched = true; }
$done(matched ? {body: JSON.stringify(o)} : {});
} catch (_) { $done({}); }
