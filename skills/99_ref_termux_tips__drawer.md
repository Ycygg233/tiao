# Termux 使用小技巧

> 优先级: ref（不自动注入，用户问到时再翻阅）
> 标签: termux, extra-keys, drawer, 全面屏

## 快速打开侧滑菜单

全面屏手势下，从屏幕边缘滑动唤出 Termux 侧滑菜单（新建窗口/切换会话）很困难。

### 解决方案

把 extra-keys 中的 `/` 键替换为 `DRAWER` 键：

```bash
# 编辑 ~/.termux/termux.properties
# 将 extra-keys 中的 '/' 替换为 'DRAWER'

extra-keys = [ \
  ['ESC','DRAWER','-','HOME','UP','END','PGUP'], \
  ['TAB','CTRL','ALT','LEFT','DOWN','RIGHT','PGDN'] \
]
```

```bash
# 使生效
termux-reload-settings
```

### 效果

底部按键出现一个 `DRAWER` 按钮，按一下即可打开侧滑菜单，无需从屏幕边缘滑动。

### 适用场景

- 开启全面屏手势的 Android 手机
- 频繁切换 Termux 多窗口的用户
