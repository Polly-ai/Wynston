// Surge equivalent of QX jsonjq-response-body: .result.list=[]
// Preserve all unrelated fields; jq accepts null/missing intermediate objects.
(function () {
  try {
    var value = JSON.parse($response.body);
    if (value === null) value = {};
    if (typeof value !== "object" || Array.isArray(value)) throw new Error("invalid root");
    if (value.result == null) value.result = {};
    if (typeof value.result !== "object" || Array.isArray(value.result)) throw new Error("invalid result");
    value.result.list = [];
    $done({body: JSON.stringify(value)});
  } catch (_) { $done({}); }
})();
