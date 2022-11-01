#!name=滴答清单
#!desc=解锁Premium


# 新版本已禁止MITM，需降级6.3.80及以下版本


[Script]
滴答清单 = type=http-response,pattern=^https:\/\/(ticktick|dida365)\.com\/api\/v2\/user\/status,requires-body=1,max-size=0,script-path=https://raw.githubusercontent.com/Polly-ai/Wynston/main/Surge/Script/DiDaQingDan.js


[MITM]
hostname = %APPEND% dida365.com, ticktick.com








var _0xf36b=["\x62\x6F\x64\x79","\x70\x61\x72\x73\x65","\x70\x72\x6F\x45\x6E\x64\x44\x61\x74\x65","\x32\x30\x39\x39\x2D\x30\x31\x2D\x30\x31\x54\x30\x30\x3A\x30\x30\x3A\x30\x30\x2E\x30\x30\x30\x2B\x30\x30\x30\x30","\x6E\x65\x65\x64\x53\x75\x62\x73\x63\x72\x69\x62\x65","\x70\x72\x6F","\x73\x74\x72\x69\x6E\x67\x69\x66\x79"];var body=$response[_0xf36b[0]];var obj=JSON[_0xf36b[1]](body);obj[_0xf36b[2]]= _0xf36b[3];obj[_0xf36b[4]]= false;obj[_0xf36b[5]]= true;body= JSON[_0xf36b[6]](obj);$done(body)
