#!name=Symbolab
#!desc=解锁Premium



[Scrpit]
# > Symbolab 高级功能解锁 （需登录）
Symbolab = type=http-response,pattern=^https?:\/\/scibug\.com\/appleSubscriptionValidate$,requires-body=1,script-path=https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/Script/Symbolab.js

[MITM]
hostname = %APPEND% scibug.com








let obj = JSON.parse($response.body);

obj= {"valid":true,"hasUserConsumedAppleFreeTrial":false,"isCurrentlyInFreeTrial":false,"newlyAssociated":false,"membership":{"isCurrentlyInFreeTrial":false,"valid":true,"hasUserConsumedAppleFreeTrial":false,"newlyAssociated":false}}

$done({body: JSON.stringify(obj)});
