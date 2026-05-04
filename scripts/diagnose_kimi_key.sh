#!/usr/bin/env bash
# 诊断 Moonshot 国内版 OPENAI_API_KEY 401 问题 (V0.15.5+)。
# 不打印 key 主体, 只输出 metadata: 前6位 / 长度 / 末尾字节 / 清洗前后 HTTP code。
#
# 使用: bash scripts/diagnose_kimi_key.sh [.env 路径, 默认 ./.env]
# 优先读 .env 文件; .env 没找到 OPENAI_API_KEY 时 fallback 读 shell env。

set -uo pipefail

ENV_FILE="${1:-.env}"

# Step 1: 找 key 来源
KEY=""
SOURCE="(未找到)"
if [ -f "$ENV_FILE" ] && grep -qE '^[[:space:]]*OPENAI_API_KEY=' "$ENV_FILE"; then
    KEY="$(grep -E '^[[:space:]]*OPENAI_API_KEY=' "$ENV_FILE" | head -1 | sed -E 's/^[[:space:]]*OPENAI_API_KEY=//')"
    SOURCE="$ENV_FILE"
fi
if [ -z "$KEY" ] && [ -n "${OPENAI_API_KEY:-}" ]; then
    KEY="$OPENAI_API_KEY"
    SOURCE="shell env"
fi
if [ -z "$KEY" ]; then
    echo "ERROR: OPENAI_API_KEY 在 $ENV_FILE 和 shell env 里都没找到"
    exit 1
fi

# Step 2: raw metadata (无清洗)
LEN_RAW=$(printf '%s' "$KEY" | wc -c | tr -d ' ')
HEAD6="${KEY:0:6}"
TAIL_OD=$(printf '%s' "$KEY" | od -c | tail -2 | head -1 | sed 's/^[0-9]\+ //')

# Step 3: 清洗 (剥 \r \n + 末尾空格)
KEY_CLEAN=$(printf '%s' "$KEY" | tr -d '\r\n' | sed 's/[[:space:]]*$//')
LEN_CLEAN=$(printf '%s' "$KEY_CLEAN" | wc -c | tr -d ' ')

echo "=== Metadata ==="
echo "Source:    $SOURCE"
echo "Head:      ${HEAD6}..."
echo "Len raw:   $LEN_RAW bytes"
echo "Len clean: $LEN_CLEAN bytes"
echo "Diff:      $((LEN_RAW - LEN_CLEAN)) bytes 被清洗剥掉"
echo "Tail od:   $TAIL_OD"
echo ""

CONTAMINATED=0
if [ "$LEN_RAW" -ne "$LEN_CLEAN" ]; then
    echo "诊断: Key 含换行符/末尾空格 (raw=$LEN_RAW > clean=$LEN_CLEAN), 极可能就是 401 主因"
    CONTAMINATED=1
else
    echo "诊断: Key 无换行污染, raw=clean, 401 不是换行问题"
fi
echo ""

# Step 4: 双 curl 验证 (raw vs clean)
echo "=== curl 验证 (api.moonshot.cn/v1/models) ==="
HTTP_RAW=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 \
    https://api.moonshot.cn/v1/models \
    -H "Authorization: Bearer $KEY" 2>/dev/null || echo "ERR")
HTTP_CLEAN=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 \
    https://api.moonshot.cn/v1/models \
    -H "Authorization: Bearer $KEY_CLEAN" 2>/dev/null || echo "ERR")
echo "Raw key:   HTTP $HTTP_RAW"
echo "Clean key: HTTP $HTTP_CLEAN"
echo ""

# Step 5: 修复指引
echo "=== 修复指引 ==="
if [ "$HTTP_CLEAN" = "200" ] && [ "$HTTP_RAW" != "200" ]; then
    echo "✓ 清洗后 200, 确诊换行污染"
    if [ "$SOURCE" = "$ENV_FILE" ]; then
        echo "→ 编辑 $ENV_FILE, 找到 OPENAI_API_KEY=<key> 行, 确保 = 后无尾随空格/换行"
        echo "  最稳: 删该行后用 read -rs OPENAI_API_KEY 重粘贴, 然后改 .env 不带换行"
    else
        echo "→ shell 重 export: read -rs OPENAI_API_KEY && export OPENAI_API_KEY"
    fi
elif [ "$HTTP_CLEAN" = "200" ] && [ "$HTTP_RAW" = "200" ]; then
    echo "✓ 双 200, key 完全 OK; pytest 401 真因可能在别处 (vcr cassette stale? .env 加载失败?)"
    echo "→ rm tests/cassettes/test_smoke_openai_kimi_real/*.yaml 后重跑 pytest"
elif [ "$HTTP_CLEAN" != "200" ]; then
    echo "✗ 清洗后仍非 200 ($HTTP_CLEAN), 不是换行问题"
    case "$HTTP_CLEAN" in
        401) echo "→ key 真无效/未实名/未充值: 去 platform.moonshot.cn/console/account 检查" ;;
        402|429) echo "→ 余额或 quota: 去 platform.moonshot.cn/console/account 充值" ;;
        ERR) echo "→ 网络无法到达 api.moonshot.cn (DNS/proxy/防火墙)" ;;
        *) echo "→ 异常 HTTP $HTTP_CLEAN, 控制台或社群求助" ;;
    esac
fi
