# Wrapper Setup Guide / Wrapper 配置教程

[English](#english) | [简体中文](#简体中文)

---

<a name="english"></a>

## English

This guide explains how to download, extract, configure, and run Wrapper on Linux.

> Wrapper requires account credentials. Only run it on a trusted computer and network. Do not share your password, 2FA verification code, token, or cached account information.

### 1. Install the Required Tools

Debian or Ubuntu:

```bash
sudo apt update && sudo apt install -y curl unzip
```

Fedora:

```bash
sudo dnf install -y curl unzip
```

Arch Linux:

```bash
sudo pacman -S --needed curl unzip
```

### 2. Download Wrapper

The following command downloads the latest Linux x86_64 release:

```bash
curl -fL "https://github.com/WorldObservationLog/wrapper/releases/download/wrapper.x86_64.latest/Wrapper.x86_64.latest.zip" -o Wrapper.x86_64.latest.zip
```

### 3. Extract Wrapper

Create a `wrapper` directory, extract the archive into it, and enter the directory:

```bash
mkdir -p wrapper
unzip Wrapper.x86_64.latest.zip -d wrapper
cd wrapper
```

Give the executable permission to run:

```bash
chmod +x wrapper
```

> Linux file names are case-sensitive. If the executable has a different name, use its exact name in the commands.

### 4. Log In and Run Wrapper

Run Wrapper with your username and password:

```bash
./wrapper -L 'username:password'
```

Replace `username` and `password` with your actual account credentials.

Example:

```bash
./wrapper -L 'user@example.com:your_password'
```

Keep the login value inside single quotes so that most special characters are not interpreted by the shell.

> The command may be stored in your shell history. Avoid running it on a shared or untrusted computer.

If two-factor authentication is enabled, Wrapper may ask you to enter a 2FA verification code. Enter the code from your trusted device when prompted.

### 5. Confirm That Wrapper Is Running

Wrapper is running normally when the terminal displays output similar to:

```text
[+] account info cached successfully
[+] StoreFront ID: 143465-2,31
[+] Music-Token: AtYyithbLKwQAX...
[!] listening m3u8 request on 127.0.0.1:20020
[!] listening 127.0.0.1:10020
[!] listening account info request on 127.0.0.1:30020
[!] listening key request on 127.0.0.1:40020
```

Keep the terminal open while using Wrapper. Closing the terminal or terminating the process will stop all Wrapper services.

By default, Wrapper listens on `127.0.0.1`, so its services are only accessible from the local computer.

### Usage

```text
Usage: wrapper [OPTION]...

  -h, --help              Print help and exit
  -V, --version           Print version and exit
  -H, --host=STRING         (default=`127.0.0.1')
  -D, --decrypt-port=INT    (default=`10020')
  -M, --m3u8-port=INT       (default=`20020')
  -A, --account-port=INT    (default=`30020')
  -K, --key-port=INT        (default=`40020')
  -P, --proxy=STRING        (default=`')
  -L, --login=STRING        (username:password)
  -F, --code-from-file      (default=off)
```

### Services

Wrapper provides services on four TCP ports:

| Port | Option | Protocol | Purpose |
|------|--------|----------|---------|
| 10020 | `-D` | Binary | Sample decryption: `[1B len][adamId][1B len][uri]`, followed by `[4B size][ciphertext]` to plaintext |
| 20020 | `-M` | Binary | M3U8 stream URL: `[1B len][adamId digits]` to an M3U8 URL |
| 30020 | `-A` | HTTP | Account information in JSON format |
| 40020 | `-K` | HTTP | Key service: `?adamId=&uri=` to a decryption template |

#### Port 40020 Key Service

Request any track once to obtain the complete content decryption template:

```bash
curl "http://127.0.0.1:40020/?adamId=1720704575&uri=skd%3A%2F%2Fitunes.apple.com%2Fp683167092%2Fc6"
```

Example response:

```json
{
  "adamId": "...",
  "keyUri": "...",
  "contentKey": "...",
  "ctx": "<base64>",
  "state": "<base64>",
  "rcx": "0x..",
  "rax": "0x..",
  "rdx": "0x..",
  "r9": "0x..",
  "rbp": "0x.."
}
```

The template is captured by a Dobby hook at the R1 entry (`libCoreLSKD+0x1d5709`) in debug builds.

### Special Thanks

- Anonymous, for providing the original version of this project and the legacy Frida decryption method.
- chocomint, for providing support for the arm64 architecture.

[Back to top](#wrapper-setup-guide--wrapper-配置教程)

---

<a name="简体中文"></a>

## 简体中文

本教程介绍如何在 Linux 系统中下载、解压、配置并运行 Wrapper。

> Wrapper 需要使用账号凭据。请仅在可信的计算机和网络环境中运行，不要向他人泄露密码、2FA 验证码、Token 或缓存的账号信息。

### 1. 安装必要工具

Debian 或 Ubuntu：

```bash
sudo apt update && sudo apt install -y curl unzip
```

Fedora：

```bash
sudo dnf install -y curl unzip
```

Arch Linux：

```bash
sudo pacman -S --needed curl unzip
```

### 2. 下载 Wrapper

运行以下命令下载最新的 Linux x86_64 版本：

```bash
curl -fL "https://github.com/WorldObservationLog/wrapper/releases/download/wrapper.x86_64.latest/Wrapper.x86_64.latest.zip" -o Wrapper.x86_64.latest.zip
```

### 3. 解压 Wrapper

创建 `wrapper` 文件夹，将压缩包解压到该文件夹，然后进入文件夹：

```bash
mkdir -p wrapper
unzip Wrapper.x86_64.latest.zip -d wrapper
cd wrapper
```

为 Wrapper 添加可执行权限：

```bash
chmod +x wrapper
```

> Linux 文件名区分大小写。如果解压后的程序名称不同，请在命令中使用它的实际名称。

### 4. 登录并运行 Wrapper

使用账号和密码运行 Wrapper：

```bash
./wrapper -L 'username:password'
```

请将 `username` 和 `password` 替换为实际的账号和密码。

示例：

```bash
./wrapper -L 'user@example.com:your_password'
```

建议使用单引号包裹登录信息，避免大多数特殊字符被 Shell 解析。

> 该命令可能会被保存在 Shell 历史记录中。请勿在共享或不可信的计算机上运行。

如果账号启用了双重认证，Wrapper 可能会要求输入 2FA 验证码。出现提示时，请输入可信设备上显示的验证码。

### 5. 确认 Wrapper 正常运行

当终端显示类似以下内容时，表示 Wrapper 已正常运行：

```text
[+] account info cached successfully
[+] StoreFront ID: 143465-2,31
[+] Music-Token: AtYyithbLKwQAX...
[!] listening m3u8 request on 127.0.0.1:20020
[!] listening 127.0.0.1:10020
[!] listening account info request on 127.0.0.1:30020
[!] listening key request on 127.0.0.1:40020
```

使用 Wrapper 时请保持终端窗口运行。关闭终端或结束 Wrapper 进程后，所有 Wrapper 服务都会停止。

Wrapper 默认监听 `127.0.0.1`，因此这些服务只能从本机访问。

### 命令行选项

```text
Usage: wrapper [OPTION]...

  -h, --help              Print help and exit
  -V, --version           Print version and exit
  -H, --host=STRING         (default=`127.0.0.1')
  -D, --decrypt-port=INT    (default=`10020')
  -M, --m3u8-port=INT       (default=`20020')
  -A, --account-port=INT    (default=`30020')
  -K, --key-port=INT        (default=`40020')
  -P, --proxy=STRING        (default=`')
  -L, --login=STRING        (username:password)
  -F, --code-from-file      (default=off)
```

### 服务端口

Wrapper 通过四个 TCP 端口提供服务：

| 端口 | 选项 | 协议 | 用途 |
|------|------|------|------|
| 10020 | `-D` | Binary | 样本解密：`[1B len][adamId][1B len][uri]`，然后通过 `[4B size][ciphertext]` 输出明文 |
| 20020 | `-M` | Binary | M3U8 流地址：通过 `[1B len][adamId digits]` 获取 M3U8 URL |
| 30020 | `-A` | HTTP | 获取 JSON 格式的账号信息 |
| 40020 | `-K` | HTTP | 密钥服务：通过 `?adamId=&uri=` 获取解密模板 |

#### 40020 密钥服务

请求任意曲目一次，即可获取完整的内容解密模板：

```bash
curl "http://127.0.0.1:40020/?adamId=1720704575&uri=skd%3A%2F%2Fitunes.apple.com%2Fp683167092%2Fc6"
```

响应示例：

```json
{
  "adamId": "...",
  "keyUri": "...",
  "contentKey": "...",
  "ctx": "<base64>",
  "state": "<base64>",
  "rcx": "0x..",
  "rax": "0x..",
  "rdx": "0x..",
  "r9": "0x..",
  "rbp": "0x.."
}
```

在调试版本中，该模板由 R1 入口处的 Dobby Hook 捕获：`libCoreLSKD+0x1d5709`。

### 特别感谢

- Anonymous，提供本项目的原始版本以及旧版 Frida 解密方法。
- chocomint，提供 arm64 架构支持。

[返回顶部](#wrapper-setup-guide--wrapper-配置教程)