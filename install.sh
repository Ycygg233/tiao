#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# 鲦 (tiao) — 一键安装脚本 v2
# 用法: bash install.sh [-y] [目标目录]
# 默认安装到 ~/tiao/
#
# 适用: Termux 首次安装 / 国内网络环境
# 耗时: 约 5~8 分钟（主要花在 pkg upgrade）
# 特性: 智能跳过已完成的步骤，可重复运行
#       自动利用 wheels/ 预编译轮子加速
# 参数:
#   -y        自动模式，换源不询问，直接换清华源
#   目标目录  安装路径（默认 ~/Documents/tiao/）
# ============================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

# ── 参数解析 ──────────────────────────────
AUTO_YES=false
INSTALL_DIR="$HOME/tiao"
while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes) AUTO_YES=true; shift ;;
        -*) echo "❌ 未知参数: $1"; exit 1 ;;
        *) INSTALL_DIR="$1"; shift ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STEP=0
TOTAL=6

echo ""
echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║    鲦 (tiao) — 一键安装脚本 v2     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
echo ""

# ── 辅助函数 ──────────────────────────────

step() { STEP=$((STEP + 1)); echo -e "${YELLOW}[${STEP}/${TOTAL}] ${1}${NC}"; }
skip() { echo -e "  ${GREEN}⏭${NC} $1"; }
ok()   { echo -e "  ${GREEN}✅${NC} $1"; }
doing(){ echo -e "  ${YELLOW}⏳${NC} $1"; }
fail() { echo -e "  ${RED}❌${NC} $1"; }

# ── 国内镜像源列表 ────────────────────────

CN_MIRRORS=(
    "mirrors.tuna.tsinghua.edu.cn"
    "mirrors.ustc.edu.cn"
    "mirrors.aliyun.com"
    "mirrors.cloud.tencent.com"
    "mirrors.163.com"
    "mirrors.huaweicloud.com"
)

is_cn_mirror() {
    local url="$1"
    for m in "${CN_MIRRORS[@]}"; do
        if echo "$url" | grep -q "$m"; then
            return 0
        fi
    done
    return 1
}

# ── 检测 Python 版本（用于匹配 wheel） ────
PY_MAJOR=""
PY_MINOR=""
detect_python_version() {
    local ver
    ver=$(python3 --version 2>/dev/null | grep -oP '\d+\.\d+')
    PY_MAJOR="${ver%.*}"
    PY_MINOR="${ver#*.}"
}

# ── 判断 wheel 是否兼容本机 Python ─────────
wheel_compatible() {
    local whl_file="$1"
    local basename
    basename=$(basename "$whl_file")

    # py3-none-any → 通用
    if echo "$basename" | grep -q 'py3-none-any'; then
        return 0
    fi

    # 提取 cp313 这样的标签
    local py_tag
    py_tag=$(echo "$basename" | grep -oP 'cp\d{2,3}(?=-)' | head -1)
    [ -z "$py_tag" ] && return 1

    local py_code="${py_tag#cp}"
    local w_major="${py_code:0:1}"
    local w_minor="${py_code:1}"

    # 去掉前导零
    w_minor=$((10#$w_minor))

    if [ "$w_major" = "$PY_MAJOR" ] && [ "$w_minor" = "$PY_MINOR" ]; then
        return 0
    fi
    return 1
}

# ── 安装 whl 目录下指定包的本地轮子 ────────
install_local_wheels() {
    local whl_dir="$1"
    shift
    local wanted_pkgs=("$@")

    [ -d "$whl_dir" ] || return 1

    local matched=()
    local whl

    for whl in "$whl_dir"/*.whl; do
        [ -f "$whl" ] || continue

        # 如果指定了想要的包列表，只处理列表中的
        if [ ${#wanted_pkgs[@]} -gt 0 ]; then
            local pkg_name
            pkg_name=$(basename "$whl" | sed -E 's/-[0-9].*//')
            local found=false
            for wanted in "${wanted_pkgs[@]}"; do
                if [ "$pkg_name" = "$wanted" ]; then
                    found=true
                    break
                fi
            done
            [ "$found" = false ] && continue
        fi

        if wheel_compatible "$whl"; then
            matched+=("$whl")
        fi
    done

    if [ ${#matched[@]} -gt 0 ]; then
        doing "安装本地预编译 wheel（${#matched[@]} 个）..."
        python3 -m pip install "${matched[@]}" --quiet 2>&1
        for whl in "${matched[@]}"; do
            echo -e "     ${GREEN}✓${NC} $(basename "$whl")"
        done
        return 0
    fi
    return 1
}

# ═══════════════════════════════════════════
# [1/6] 软件源配置
# ═══════════════════════════════════════════
step "软件源配置"

SOURCES_FILE="$PREFIX/etc/apt/sources.list"
CURRENT_SOURCE=""
if [ -f "$SOURCES_FILE" ]; then
    CURRENT_SOURCE=$(grep -oP 'https?://[^/]+/termux' "$SOURCES_FILE" 2>/dev/null | head -1)
    [ -z "$CURRENT_SOURCE" ] && CURRENT_SOURCE=$(grep -oP 'deb\s+\S+' "$SOURCES_FILE" 2>/dev/null | head -1)
fi

if is_cn_mirror "$CURRENT_SOURCE"; then
    ok "软件源已是国内镜像"
elif echo "$CURRENT_SOURCE" | grep -q "packages.termux.org"; then
    if [ "$AUTO_YES" = true ]; then
        sed -i 's@packages.termux.org@mirrors.tuna.tsinghua.edu.cn/termux@' "$SOURCES_FILE"
        ok "已自动切换为清华源（-y 模式）"
    else
        doing "检测到默认官方源（国内较慢）"
        echo -e "  ${YELLOW}🌐 推荐切换为清华源加速下载${NC}"
        echo -e "  ${YELLOW}⏳ 是否换源？[Y/n]${NC} "
        read -r _auto_mirror
        if [[ "$_auto_mirror" =~ ^[Yy]?$ ]]; then
            sed -i 's@packages.termux.org@mirrors.tuna.tsinghua.edu.cn/termux@' "$SOURCES_FILE"
            ok "已切换为清华源"
        else
            echo -e "  ${YELLOW}⏭  跳过换源${NC}"
        fi
    fi
else
    ok "软件源已配置（第三方源），跳过"
fi
echo ""

# ═══════════════════════════════════════════
# [2/6] 系统更新
# ═══════════════════════════════════════════
step "系统更新"

UPGRADABLE=$(pkg list-upgradable 2>/dev/null | grep -c . || true)
if [ "$UPGRADABLE" -eq 0 ]; then
    ok "系统已最新，跳过 upgrade"
else
    doing "pkg update..."
    pkg update -y -qq 2>/dev/null || { fail "pkg update 失败"; exit 1; }
    doing "pkg upgrade（${UPGRADABLE} 个可更新）..."
    pkg upgrade -y -qq 2>/dev/null || { fail "pkg upgrade 失败"; exit 1; }
    ok "系统已更新"
fi
echo ""

# ═══════════════════════════════════════════
# [3/6] Python 环境
# ═══════════════════════════════════════════
step "Python 环境"

if command -v python3 &>/dev/null; then
    ok "Python: $(python3 --version)"
else
    doing "安装 python..."
    pkg install python -y -qq
    ok "Python: $(python3 --version)"
fi

if python3 -m pip --version &>/dev/null; then
    ok "pip: $(python3 -m pip --version 2>/dev/null | head -1)"
else
    doing "安装 python-pip..."
    pkg install python-pip -y -qq
    ok "pip: $(python3 -m pip --version 2>/dev/null | head -1)"
fi

detect_python_version
echo -e "  ${DIM}  Python ${PY_MAJOR}.${PY_MINOR} — 将匹配 cp${PY_MAJOR}${PY_MINOR} 标签的 wheel${NC}"
echo ""

# ═══════════════════════════════════════════
# [4/6] 系统依赖（可选）
# ═══════════════════════════════════════════
step "系统依赖（可选）"

if command -v termux-clipboard-get &>/dev/null; then
    ok "termux-api 已安装"
else
    doing "安装 termux-api..."
    if pkg install termux-api -y -qq 2>/dev/null; then
        ok "termux-api 安装完成"
    else
        echo -e "  ${YELLOW}⚠️  安装失败，paste 工具不可用（不影响核心功能）${NC}"
    fi
fi
echo ""

# ═══════════════════════════════════════════
# [5/6] Python 依赖
# ═══════════════════════════════════════════
step "Python 依赖"

WHEEL_DIR="$SCRIPT_DIR/wheels"

# ── 优先安装本地 wheel ─────────────────────
if [ -d "$WHEEL_DIR" ] && ls "$WHEEL_DIR"/*.whl &>/dev/null; then
    echo -e "  ${DIM}  发现 $(ls "$WHEEL_DIR"/*.whl 2>/dev/null | wc -l) 个预编译 wheel${NC}"

    # 单独装 pydantic_core（fastapi 的 C 核心，必须先装）
    for whl in "$WHEEL_DIR"/pydantic_core-*.whl; do
        [ -f "$whl" ] || continue
        if wheel_compatible "$whl"; then
            doing "安装 pydantic_core（预编译）..."
            python3 -m pip install "$whl" --quiet 2>&1 && \
                echo -e "     ${GREEN}✓${NC} $(basename "$whl")"
        fi
        break
    done

    # 批量装其余 wheel（tiktoken, pyyaml, regex, tree_sitter, watchdog, maturin）
    # 按优先级排列
    install_local_wheels "$WHEEL_DIR" \
        tiktoken pyyaml regex tree_sitter watchdog maturin

else
    echo -e "  ${DIM}  wheels/ 为空，全走在线安装${NC}"
fi

# ── 补充安装 requirements.txt 完整依赖 ──────
doing "安装 requirements.txt 所有依赖..."

# 先确保纯 Python 核心包
python3 -m pip install rich prompt_toolkit requests --quiet 2>&1
for pkg in rich prompt_toolkit requests; do
    if python3 -m pip show "$pkg" &>/dev/null; then
        ver=$(python3 -m pip show "$pkg" 2>/dev/null | grep -i "^version:" | awk '{print $2}')
        echo -e "     ${GREEN}✓${NC} $pkg == $ver"
    fi
done

# 装 requirements.txt（会利用已装的 wheel 跳过编译）
REQ_FILE="$SCRIPT_DIR/requirements.txt"
if [ -f "$REQ_FILE" ]; then
    python3 -m pip install -r "$REQ_FILE" --quiet 2>&1 || {
        echo -e "  ${YELLOW}⚠️  批量安装部分失败，逐包尝试...${NC}"
        while IFS= read -r line; do
            [[ -z "$line" || "$line" =~ ^# ]] && continue
            pkg_name=$(echo "$line" | sed -E 's/[><=!~].*//' | xargs)
            [ -z "$pkg_name" ] && continue

            if python3 -m pip show "$pkg_name" &>/dev/null; then
                echo -e "     ${GREEN}✓${NC} $pkg_name"
            else
                doing "  $pkg_name..."
                python3 -m pip install "$pkg_name" --quiet 2>&1 && \
                    echo -e "     ${GREEN}✓${NC} $pkg_name" || \
                    echo -e "     ${YELLOW}⚠️  $pkg_name 失败${NC}"
            fi
        done < "$REQ_FILE"
    }
fi

# ── 验证关键包 ────────────────────────────
echo ""
doing "验证关键依赖..."
for pkg in rich prompt_toolkit requests PyYAML tiktoken fastapi uvicorn httpx; do
    if python3 -m pip show "$pkg" &>/dev/null; then
        ver=$(python3 -m pip show "$pkg" 2>/dev/null | grep -i "^version:" | awk '{print $2}')
        echo -e "     ${GREEN}✓${NC} $pkg == $ver"
    else
        echo -e "     ${RED}✗${NC} $pkg（未安装）"
    fi
done
echo ""

# ═══════════════════════════════════════════
# [6/6] 部署 & 启动配置
# ═══════════════════════════════════════════
step "部署 & 启动配置"

ALREADY_DEPLOYED=false
[ -f "$INSTALL_DIR/main.py" ] && [ -f "$INSTALL_DIR/config.py" ] && ALREADY_DEPLOYED=true

if [ "$SCRIPT_DIR" = "$INSTALL_DIR" ]; then
    skip "已在目标目录，跳过复制"
elif [ "$ALREADY_DEPLOYED" = true ]; then
    skip "项目文件已存在，跳过复制"
else
    doing "部署到 ${INSTALL_DIR}..."
    mkdir -p "$INSTALL_DIR"

    # 根目录文件
    for item in \
        main.py config.py session.py styles.py \
        requirements.txt README.md \
        install.sh tiao.sh provider-key.sh; do
        [ -e "$SCRIPT_DIR/$item" ] && cp "$SCRIPT_DIR/$item" "$INSTALL_DIR/"
    done

    # 核心子目录
    for dir in chat commands tools utils security skills \
               icon web; do
        [ -d "$SCRIPT_DIR/$dir" ] && cp -r "$SCRIPT_DIR/$dir" "$INSTALL_DIR/"
    done

    # wheels/
    if [ -d "$SCRIPT_DIR/wheels" ] && ls "$SCRIPT_DIR/wheels"/*.whl &>/dev/null; then
        mkdir -p "$INSTALL_DIR/wheels"
        cp "$SCRIPT_DIR/wheels"/*.whl "$INSTALL_DIR/wheels/"
    fi

    # YAML 配置（已在 security/ 目录中）

    # 数据目录（~/.tiao_data/）
    DATA_DIR="$HOME/.tiao_data"
    for dir in sessions logs search_cache; do
        mkdir -p "$DATA_DIR/$dir"
    done

    # .gitignore
    if [ ! -f "$INSTALL_DIR/.gitignore" ]; then
        cat > "$INSTALL_DIR/.gitignore" << 'GITIGNORE'
__pycache__/
.pytest_cache/
.session/
*.pyc
*.tmp
*.bak
_smoke_tmp/
wheels/
GITIGNORE
    fi

    ok "文件部署完成（含 wheels/ 预编译包）"
fi
echo ""

# ── 启动别名 ───────────────────────────────
ALIAS_TIAO="alias tiao='cd ${INSTALL_DIR} && python3 main.py'"
ALIAS_AI="alias ai='cd ${INSTALL_DIR} && python3 main.py'"
ALIAS_WEB="alias tiao-web='cd ${INSTALL_DIR} && python3 main.py -web'"
BASHRC="$HOME/.bashrc"

if grep -qx "alias tiao=" "$BASHRC" 2>/dev/null; then
    skip "启动别名 'tiao' 已存在"
else
    echo "" >> "$BASHRC"
    echo "# 鲦 (tiao) AI 助手" >> "$BASHRC"
    echo "$ALIAS_TIAO" >> "$BASHRC"
    echo "$ALIAS_AI" >> "$BASHRC"
    echo "$ALIAS_WEB" >> "$BASHRC"
    ok "别名已写入 ~/.bashrc"
    echo -e "     ${CYAN}tiao${NC} — 启动 AI 助手"
    echo -e "     ${CYAN}ai${NC} — 启动 AI 助手（别名）"
    echo -e "     ${CYAN}tiao-web${NC} — 启动 Web 模式"
fi
echo ""

# ═══════════════════════════════════════════
# 完成
# ═══════════════════════════════════════════
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ 安装完成！                     ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "  项目路径: ${CYAN}${INSTALL_DIR}${NC}"
echo -e "  启动命令: ${CYAN}tiao${NC}  或  ${CYAN}ai${NC}  或  ${CYAN}cd ${INSTALL_DIR} && python3 main.py${NC}"
echo ""

KEY_FILE="$HOME/.tiao_key"
if [ ! -f "$KEY_FILE" ] && [ -z "$TIAO_KEY" ]; then
    echo -e "  ${YELLOW}🔑 首次运行会提示输入 DeepSeek API Key${NC}"
    echo -e "  获取地址: ${CYAN}https://platform.deepseek.com/api_keys${NC}"
else
    echo -e "  ${GREEN}🔑 API Key 已配置${NC}"
fi
echo ""

WHEEL_COUNT=$(ls "$SCRIPT_DIR/wheels"/*.whl 2>/dev/null | wc -l)
echo -e "  ${DIM}📦 已纳入 ${WHEEL_COUNT} 个预编译 wheel${NC}"
echo -e "  ${DIM}💡 pip install 将优先使用本地 wheel，跳过编译${NC}"
echo ""
