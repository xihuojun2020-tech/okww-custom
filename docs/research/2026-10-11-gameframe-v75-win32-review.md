# v75 Win32 capture/input 与 overlay 只读接口复核

本次比对已发布 v74 生产 Windows device/editor 与 v75-staging 候选，合并显式 capture/input 选项，并新增 UID overlay 需要的只读设备接口。修改范围：`gameframe/devices/windows.py`、`gameframe/device_editor.py`、`tests/TestGameFrameWin32Options.py`。保留 v74 的 `desktop-handoff`；未修改版本或发布。没有加载真实 Win32 DLL、发送系统输入、启动游戏或访问 NAS。

## 行为与依据

默认仍是 WGC 与前台 SendInput。显式选项为 WGC、BitBlt_RenderFull、PrintWindow，以及 SendInput、PostMessage。DeviceEditor 保存的是 WindowsDevice 实际执行的参数；切换 PostMessage 后 editor 与实例均移除 relative-mouse 能力，保留 desktop-handoff。旧 JSON 没有新字段时仍使用原默认路径。

PrintWindow 客户区方式在内存 DC 中渲染；BitBlt_RenderFull 先在内存 DC 中渲染完整窗口，再裁剪客户区到独立 DIB，最后返回拥有自身内存的连续 BGR 数组。每次读取分配并回收 DC/bitmap，DPI context 恢复；不向窗口 DC 写入，也没有捕获失败转 WGC 的隐式 fallback。最小化和空客户区会明确拒绝。同步 PrintWindow 的 API 不保证响应速度、新鲜图像、最小化支持或游戏接受度。

PostMessage 只投递窗口消息。实现目标 HWND/PID/create_time 校验、物理客户坐标至目标 DPI 逻辑坐标转换、修饰键、滚轮、extended/repeat/key-up 位、Alt/F10 系统键及 UTF-16 WM_CHAR。成功返回代表消息成功入队，不能证明游戏响应。它不发送 raw relative mouse，也不移动物理桌面光标。失败的 key-up 保留持有记录以便显式后续释放；目标身份变化时拒绝向新窗口释放或发送。激活仍须显式 activate 动作。

## overlay_target 契约

`WindowsDevice.overlay_target()` 返回 None 或：

```python
{'owner': {'hwnd': int, 'pid': int, 'created': float},
 'x': int, 'y': int, 'width': int, 'height': int}
```

几何是物理像素下客户区的屏幕矩形，允许多显示器负原点。`_WindowBackend.client_screen_rect` 在同一 thread DPI scope 内读取 GetClientRect 和 ClientToScreen。设备只允许当前 selected HWND 本身为前台；关闭、尚未绑定、不存在、PID/create_time 改变、空客户区或几何读取期间前台/选中目标/身份变化均返回 None。psutil.NoSuchProcess 按进程消失返回 None，其他实际 backend 故障传播给 UI 边界。该接口不导入 Qt、不 capture、不 activate、不构建输入 backend，也不发送任何动作。

身份与几何两侧的复核依据是外部 HWND 可消失/复用，以及 UID mask 不得显示到不同的前台目标。它不能保证窗口在调用返回之后仍然不变；overlay 消费者须用本次 owner 更新自身目标，不应把返回值当长期身份授权。

## 最小验证

测试改为正常 production imports，支持安装目录导入验收；删除 staged_module 别名、复制源码叠加伪安装和模块顶层 ctypes.WinDLL 替换。每项测试的 scoped DLL guard 在 cleanup 中恢复，不污染其他 tests。注入 fake API，Qt 使用 offscreen 表单，没有真实 OS 窗口枚举或设备操作。

`TestGameFrameWin32Options.py`：15 项通过。覆盖 GDI BGR/resize/copy/完整窗口裁剪/资源回收/失败及最小化拒绝；PostMessage DPI/修饰键/滚轮/键位/Unicode/保留释放/身份变化/重绑定；表单保存/default/capabilities 和生产 create_device JSON 惰性构造；overlay owner/物理坐标/只读/不存在/后台/复用/几何竞态及 DPI scope。

`TestGameFrameDevices.py`：16 项通过，原有默认设备路径检查保持通过。新增 selected-target 几何竞态后只重跑受影响的选项文件；原有设备检查未重复扩展。

这些是离线接口和资源所有权检查。真实游戏的 GDI 图像质量、PrintWindow 阻塞、后台消息接受、真实 DPI/多显示器和 UID overlay 展示仍需实际运行验证，不能以 fake 通过替代。
