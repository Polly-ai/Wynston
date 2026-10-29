// VVeboFans_surge.js - 源自 suiyuran/stash 的 fix-vvebo-fans.js，逻辑原样保留
// 该脚本不使用 QX 专属 API，Surge 下无需改动；仅加本行来源注释。
const url = $request.url;

if (url.includes("selffans")) {
  const data = JSON.parse($response.body);
  const cards = data.cards.filter((card) => card.itemid !== "INTEREST_PEOPLE2");
  const body = JSON.stringify({ ...data, cards });
  $done({ body });
} else {
  $done({});
}
