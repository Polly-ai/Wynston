#!name=Tidal
#!desc=解锁Premium




[Script]
TIDAL = type=http-request,pattern=^https?:\/\/api\.tidal\.com\/v1\/(pages\/album|(user|track|page)s\/(\d+)\/(state|subscription|lyrics|onboarding|playbackinfopostpaywall)),requires-body=0,script-path=https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/Script/TIDALHiFiPlusCrack.js

[MITM]
hostname = %APPEND% api.tidal.com











$done({
    body: JSON.stringify({
        "status": "ACTIVE",
        "canGetTrial": false,
        "startDate": "2019-09-28T09:09:09.000+0000",
        "subscription": {
            "type": "PREMIUM_PLUS",
            "offlineGracePeriod": 999999
        },
        "premiumAccess": true,
        "paymentType": "ADYEN_CREDIT_CARD",
        "paymentOverdue": false,
        "highestSoundQuality": "HI_RES",
        "validUntil": "2999-09-28T09:09:09.000+0000"
    })
});
