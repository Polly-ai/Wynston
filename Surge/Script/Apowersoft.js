# 傲软抠图解锁VIP
# 下载地址:https://apps.apple.com/cn/app/id1490054676
# 脚本作者:墨鱼



QuantumultX


[rewrite_local]
https?:\/\/.*\.aoscdn\.com\/base\/vip\/client\/authorizations$ url script-response-body https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/Script/Apowersoft.js

[mitm] 
hostname=*.aoscdn.com


Surge

[Script]
Apowersoft = type=http-response,pattern=https?:\/\/.*\.aoscdn\.com\/base\/vip\/client\/authorizations$,requires-body=1,max-size=0,script-path=https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/Script/Apowersoft.js

[MITM]
hostname = %APPEND% *.aoscdn.com















var cuttlefish ={"warning":"本腳本僅供學習交流使用，禁止轉載售賣","tgchannel":"https://t.me/ddgksf2021","feedback":"https://t.me/ddgksf2013_bot"};
var ddgksf2013 = {
  "status" : 200,
  "message" : "success",
  "data" : {
    "expired_at" : 4045798296,
    "is_activated" : 1,
    "is_lifetime" : 1,
    "expire_time" : "2099-01-01 00:00:00",
    "device_id" : 600150864,
    "period_type" : "active",
    "remain_days" : 99999,
    "product_id" : 369,
    "has_present" : 0,
    "allowed_device_count" : 1,
    "has_buy_extend" : 0,
    "will_expire" : 0,
    "license_type" : "premium",
    "begin_activated_time" : 1645798296,
    "durations" : 0,
    "vip_special" : 1
  }
};
$done({body: JSON.stringify(ddgksf2013)});
