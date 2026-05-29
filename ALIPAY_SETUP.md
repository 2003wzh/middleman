# 支付宝扫码支付接入信息清单

目标：接入支付宝当面付接口，让后端为每个订单生成专属二维码，并通过支付宝回调自动确认付款和发放 API key。

## 你需要找的信息

### 1. 商户号 / PID

当前位置：支付宝商家平台 -> 账号中心 -> 商户信息。

截图里的“商户号”或“收单账号”就是后续配置里的 `ALIPAY_SELLER_ID`。

### 2. 是否开通当面付

位置：支付宝商家平台或支付宝开放平台 -> 产品中心。

搜索并确认已开通：

```text
当面付
```

如果没开通，先按页面提示签约/开通。

### 3. APPID

位置：支付宝开放平台 -> 控制台 -> 应用。

选择已有应用，或创建一个网页/移动应用/自研应用。进入应用详情后复制：

```text
APPID
```

### 4. 密钥配置

位置：支付宝开放平台 -> 应用详情 -> 开发设置 -> 接口加签方式。

优先选择：

```text
公钥模式 / RSA2
```

流程：

1. 用支付宝密钥工具生成“应用私钥”和“应用公钥”。
2. 把“应用公钥”上传到支付宝开放平台。
3. 支付宝会生成或展示“支付宝公钥”。
4. 本地保存“应用私钥”和“支付宝公钥”。

不要把应用私钥发到聊天里。

### 5. HTTPS 回调地址

支付宝异步通知需要公网 HTTPS 地址，例如：

```text
https://你的域名/api/pay/alipay/notify
```

本地测试可以先用 ngrok、cpolar、frp 之类工具把 `http://localhost:8000` 暴露成 HTTPS。

## 最终本地配置

建议放进本地 `.env` 或启动环境变量：

```text
ALIPAY_APP_ID=你的APPID
ALIPAY_SELLER_ID=你的商户号或PID
ALIPAY_NOTIFY_URL=https://你的域名/api/pay/alipay/notify
ALIPAY_GATEWAY=https://openapi.alipay.com/gateway.do
ALIPAY_PRIVATE_KEY_PATH=./secrets/alipay_private_key.pem
ALIPAY_PUBLIC_KEY_PATH=./secrets/alipay_public_key.pem
```

私钥文件放这里：

```text
secrets/alipay_private_key.pem
```

支付宝公钥放这里：

```text
secrets/alipay_public_key.pem
```

## 可以发给 Codex 的内容

可以发：

```text
APPID
商户号 / PID
是否已开通当面付
你准备用的 notify_url
你选择的是公钥模式还是证书模式
```

不要发：

```text
应用私钥
登录密码
支付密码
短信验证码
```
