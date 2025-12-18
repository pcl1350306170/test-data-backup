2025/12/18
---
你可以使用以下 JavaScript 方法，将任意类型的数据（字符串、对象、数组等）以带时间戳的格式保存到 `localStorage` 中，并限制最多只保留 **10 条**记录，超出则自动丢弃最旧的一条。

---

### ✅ 方法实现

```js
/**
 * 将数据安全地保存到 localStorage，最多保留 10 条带时间戳的记录
 * @param {string} key - localStorage 的键名
 * @param {*} data - 要保存的数据（支持 string / number / boolean / object / array 等）
 */
function saveLogToLocalStorage(key, data) {
  try {
    // 获取当前时间（ISO 字符串，可读性强）
    const timestamp = new Date().toISOString();

    // 序列化传入的数据（兼容对象/数组/基本类型）
    const serializedData = JSON.stringify(data);

    // 从 localStorage 读取现有日志（如果存在）
    let logs = [];
    const stored = localStorage.getItem(key);
    if (stored) {
      try {
        logs = JSON.parse(stored);
        // 容错：确保是数组
        if (!Array.isArray(logs)) logs = [];
      } catch (e) {
        console.warn('Invalid log format in localStorage, resetting.');
        logs = [];
      }
    }

    // 添加新日志项：{ time: 'xxx', data: 'xxx' }
    logs.push({
      time: timestamp,
      data: serializedData
    });

    // 只保留最新的 10 条
    if (logs.length > 10) {
      logs = logs.slice(-10); // 保留后 10 条（最新）
    }

    // 保存回 localStorage
    localStorage.setItem(key, JSON.stringify(logs));

  } catch (error) {
    // 防止 localStorage 满了或被禁用导致崩溃
    console.error('Failed to save log to localStorage:', error);
  }
}
```

---

### 🔍 使用示例

```js
// 保存字符串
saveLogToLocalStorage('myAppLogs', '用户点击了按钮');

// 保存对象
saveLogToLocalStorage('myAppLogs', { action: 'login', userId: 123 });

// 保存数组
saveLogToLocalStorage('myAppLogs', [1, 2, 3, 'test']);

// 保存错误信息
saveLogToLocalStorage('myAppLogs', new Error('网络超时').stack);
```

---

### 📖 查看保存的日志（调试用）

你可以在浏览器控制台执行以下代码查看内容（虽然你说不能输出日志，但开发时可用）：

```js
JSON.parse(localStorage.getItem('myAppLogs'))
```

每条日志格式为：

```json
{
  "time": "2025-12-18T09:30:45.123Z",
  "data": "{\"action\":\"login\",\"userId\":123}"
}
```

> 💡 注意：`data` 字段是 **双重 JSON 编码** 的字符串，读取时需 `JSON.parse(item.data)` 才能得到原始值。

---

### ✅ 特性总结

- ✅ 支持任意 JS 数据类型（通过 `JSON.stringify` 序列化）
- ✅ 自动添加 ISO 8601 时间戳
- ✅ 最多保留 10 条，自动丢弃最旧记录
- ✅ 容错处理：防止 localStorage 格式错误或满容量崩溃
- ✅ 无依赖，纯原生 JS

---

### ⚠️ 注意事项

- 如果传入的数据包含 **函数、undefined、Symbol**，`JSON.stringify` 会忽略或转为 `null`。
- `localStorage` 有 **5~10MB 容量限制**，但 10 条日志通常远低于此。
- 在隐私模式或禁用 localStorage 的浏览器中会静默失败（已用 try-catch 保护）。

---

你可以直接将 `saveLogToLocalStorage` 函数复制到你的项目中使用，例如在 Vue 组件的 methods 里调用它来替代 `console.log`。
