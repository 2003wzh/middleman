# Codex 自动部署原型

这是一个最小可用版本，用网页生成 Windows PowerShell 部署命令，并由 `install-codex.ps1` 在目标电脑上安装 Codex CLI。

不能保证所有电脑 100% 成功。目标电脑的网络、代理、DNS、杀毒软件、PowerShell 策略、公司管控和用户权限都会影响部署。这个脚本会先做网络预检，失败时优先提示代理问题。

## 本地启动

在当前目录启动服务：

```powershell
$env:ADMIN_TOKEN="换成你自己的管理密码"
$env:PAY_WECHAT_ACCOUNT="你的微信收款信息"
$env:PAY_ALIPAY_ACCOUNT="你的支付宝收款信息"
$env:PAY_ALIPAY_QR="/assets/alipay-qr.png"
$env:PAY_USDT_ADDRESS="你的 USDT 地址"
$env:PAY_USDT_NETWORK="TRC20"
python .\server.py
```

然后打开：

```text
http://localhost:8000
```

管理端：

```text
http://localhost:8000/admin.html
```

如果当前 PowerShell 终端显示中文乱码，不影响浏览器页面。也可以先执行：

```powershell
chcp 65001
```

## 目标电脑执行

网页会生成类似下面的命令：

```powershell
powershell -ExecutionPolicy Bypass -EncodedCommand ...
```

把命令复制到目标电脑的 PowerShell 里执行即可。

## 脚本参数

```powershell
.\install-codex.ps1 -Method Official
.\install-codex.ps1 -Method Npm
.\install-codex.ps1 -ApiKey "sk-..."
.\install-codex.ps1 -ProxyUrl "http://127.0.0.1:7890"
.\install-codex.ps1 -SkipApiKey
.\install-codex.ps1 -SkipNetworkCheck
.\install-codex.ps1 -Force
```

## 代理说明

如果目标电脑访问不了 OpenAI、GitHub 或安装脚本，可以填写目标电脑可用的 HTTP/HTTPS 代理地址，例如：

```text
http://127.0.0.1:7890
http://127.0.0.1:10809
http://proxy.company.com:8080
```

代理软件或公司代理必须已经在目标电脑上可用。只填写一个网页地址不能自动获得代理能力。

请提前告知用户：目标电脑必须自带可用代理/VPN，或能直接访问 Codex 安装所需网络。没有代理/VPN 的用户请先前往：

```text
https://grrrs.sdkdns1.com/#/register?code=5PQ8BcLH
```

## 正式化建议

当前原型支持直接传入你已有的 API key，但正式部署时不建议把 key 长期放在可复制命令里。更好的方式是：

1. 网页生成一次性 token。
2. 脚本携带 token 调用你的后端。
3. 后端分配你已有 key 池里的某个 key。
4. 脚本把独立 key 写入目标电脑。
5. 后台保留吊销、限额、部署日志。

## API key 售卖流程

真实 API key 放在：

```text
data/api_keys.json
```

按套餐放入你的 key：

```json
{
  "plans": {
    "5": [{ "key": "sk-...", "used": false, "orderId": "", "issuedAt": "" }],
    "10": [{ "key": "sk-...", "used": false, "orderId": "", "issuedAt": "" }],
    "20": [{ "key": "sk-...", "used": false, "orderId": "", "issuedAt": "" }]
  }
}
```

用户在首页选择 5 元、10 元或 20 元套餐并提交订单。你确认收款后，进入管理端，输入 `ADMIN_TOKEN`，点击“确认收款并发放”，系统会从对应套餐 key 池里取一个未使用的 key 发给这个订单。

当前支付流程是半自动：

1. 用户选择套餐和支付方式。
2. 系统生成订单号和查询码。
3. 用户按页面显示的收款账号付款，付款备注填写订单号。
4. 你在管理端核对到账。
5. 你点击“确认收款并发放”。
6. 用户用订单号和查询码查询并领取 API key。

查询码用于防止别人只靠猜订单号拿到已发放的 key。

## 支付宝二维码

临时使用个人支付宝收款时，建议直接用支付宝 App 的收钱码图片：

1. 打开支付宝 App。
2. 进入“收钱”。
3. 保存或截图你的收款二维码。
4. 放到项目路径：

```text
assets/alipay-qr.png
```

服务默认会在用户选择支付宝订单时展示这个二维码。也可以用环境变量换成其他路径：

```powershell
$env:PAY_ALIPAY_QR="/assets/你的图片.png"
```

不要用手机号、邮箱或支付宝账号自己生成普通二维码。那只是文本二维码，不等于支付宝收款码。

不要把真实 API key 写入 `index.html`。静态网页里的内容对用户完全可见。

## 自动支付说明

真正自动确认付款需要接支付平台回调，例如微信支付、支付宝或第三方支付网关。一般需要商户号、API 密钥/证书、公网 HTTPS 回调地址，并在回调里验签后再自动调用发放逻辑。没有支付回调前，系统只能做手动确认收款。
