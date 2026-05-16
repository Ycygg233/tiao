#!/usr/bin/env bash
# provider-key.sh — 管理 Provider API Key 环境变量
# 用法:
#   ./provider-key.sh set <provider> <key>    # 设置 key
#   ./provider-key.sh list                     # 列出所有已设置的 key
#   ./provider-key.sh unset <provider>         # 删除某个 key
#   ./provider-key.sh load                     # 输出 source 语句（用于 eval）
#   ./provider-key.sh help                     # 显示此帮助

ENV_FILE="$HOME/.tiao_providers_env"

# ── 确保文件存在 ──
[[ -f "$ENV_FILE" ]] || touch "$ENV_FILE"

# ── 函数 ──

cmd_set() {
    local provider="$1"
    local key="$2"
    if [[ -z "$provider" || -z "$key" ]]; then
        echo "❌ 用法: $0 set <provider> <key>"
        exit 1
    fi
    # 如果已有该 provider 的条目则替换，否则追加
    local var_name="${provider}_api_key"
    if grep -q "^export ${var_name}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^export ${var_name}=.*|export ${var_name}=\"${key}\"|" "$ENV_FILE"
        echo "🔄 已更新 ${provider} API Key"
    else
        echo "export ${var_name}=\"${key}\"" >> "$ENV_FILE"
        echo "✅ 已设置 ${provider} API Key"
    fi
    echo "   执行以下命令加载到当前 shell:"
    echo "   source $ENV_FILE"
}

cmd_list() {
    if [[ ! -s "$ENV_FILE" ]]; then
        echo "(无已设置的 Key)"
        return
    fi
    echo "📋 已保存的 Provider Key:"
    while IFS='=' read -r var value; do
        local name="${var#export }"
        name="${name%_api_key}"
        local val="${value%\"}"
        val="${val#\"}"
        local masked="${val:0:4}...${val: -4}"
        printf "   %-15s  %s\n" "$name" "$masked"
    done < <(grep "^export.*_api_key=" "$ENV_FILE")
}

cmd_unset() {
    local provider="$1"
    if [[ -z "$provider" ]]; then
        echo "❌ 用法: $0 unset <provider>"
        exit 1
    fi
    local var_name="${provider}_api_key"
    if grep -q "^export ${var_name}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "/^export ${var_name}=/d" "$ENV_FILE"
        echo "🗑️  已移除 ${provider} API Key"
    else
        echo "⚠️   未找到 ${provider} 的 Key"
    fi
}

cmd_load() {
    echo "source $ENV_FILE"
}

# ── 入口 ──

case "${1:-help}" in
    set)    shift; cmd_set "$@" ;;
    list)   cmd_list ;;
    unset)  shift; cmd_unset "$@" ;;
    load)   cmd_load ;;
    help|*) 
        sed -n '2,8p' "$0"
        echo ""
        echo "示例:"
        echo "  # AI 平台"
        echo "  ./provider-key.sh set siliconflow sk-xxx"
        echo "  ./provider-key.sh set zhipu      xxx"
        echo "  ./provider-key.sh set deepseek   sk-xxx"
        echo ""
        echo "  # 搜索平台"
        echo "  ./provider-key.sh set metaso     xxx"
        echo "  ./provider-key.sh set tavily     tvly-xxx"
        echo "  ./provider-key.sh set jina       jina_xxx"
        echo "  ./provider-key.sh set bocha      sk-xxx"
        echo ""
        echo "  ./provider-key.sh list"
        echo "  ./provider-key.sh unset metaso"
        echo "  eval \$(./provider-key.sh load)    # 立即加载到当前 shell"
        ;;
esac
