(function () {
    const url = new URL(window.location.href);

    // ===== Toast 提示 =====
    function showToast(message, type) {
        let toast = document.getElementById('tple-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'tple-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.className = 'show' + (type ? ' ' + type : '');
        setTimeout(() => { toast.className = ''; }, 2500);
    }

    // ===== 判断是否为纯数字IP地址 =====
    function isNumericIP(hostname) {
        return /^\d{1,3}(\.\d{1,3}){3}$/.test(hostname);
    }

    // ==============================
    // 操作弹窗
    // ==============================
    function showOperationDialog(sqlType, title, apiBaseUrl) {
        const existing = document.getElementById('ward-dialog-overlay');
        if (existing) existing.remove();

        const dbHost = url.hostname;
        const apiUrl = apiBaseUrl + '/yh-mock/create-host-data';

        const overlay = document.createElement('div');
        overlay.id = 'ward-dialog-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'ward-dialog';

        // 操作类型对应的字段配置
        const fieldConfig = {
            insertUser:     { label: '添加的账号名',     name: 'username_emp',     placeholder: '如 gz',          defaultVal: 'gz' },
            deleteip:       { label: '需要删除设备的IP', name: 'deleteip',         placeholder: '如 192.168.3.199', defaultVal: '' },
            addlabelclass:  { label: '添加分类数量',     name: 'addlabelclassnum', placeholder: '如 5',           defaultVal: '5' },
            addlabel:       { label: '添加护理标签数量', name: 'addlabelnum',      placeholder: '如 15',          defaultVal: '15' }
        };
        const field = fieldConfig[sqlType];

        dialog.innerHTML = `
            <div class="ward-dialog-header">
                <span>${title}</span>
                <span class="ward-dialog-close">&times;</span>
            </div>
            <div class="ward-dialog-body">
                <div class="ward-form-row">
                    <div class="ward-form-group">
                        <label>数据库地址</label>
                        <input type="text" name="dbHost" value="${dbHost}" placeholder="自动从页面URL提取">
                    </div>
                    <div class="ward-form-group">
                        <label>端口</label>
                        <input type="text" name="dbPort" value="3306">
                    </div>
                </div>
                <div class="ward-form-row">
                    <div class="ward-form-group">
                        <label>数据库名</label>
                        <input type="text" name="dbName" value="YHDB">
                    </div>
                    <div class="ward-form-group">
                        <label>用户名</label>
                        <input type="text" name="username" value="root">
                    </div>
                </div>
                <div class="ward-form-group">
                    <label>密码</label>
                    <input type="text" name="password" value="Yahua@3585668" list="ward-pwd-list">
                    <datalist id="ward-pwd-list">
                        <option value="Yahua@3585668">4.0</option>
                        <option value="Yahua3585668yh">3.0</option>
                        <option value="123456">123456</option>
                    </datalist>
                </div>
                <div class="ward-form-group">
                    <label>${field.label}</label>
                    <input type="text" name="opValue" value="${field.defaultVal}" placeholder="${field.placeholder}">
                </div>
                <div class="ward-form-group ward-checkbox-row">
                    <label><input type="checkbox" name="directExecution"> 直接执行SQL</label>
                    <span class="ward-hint">勾选后生成并执行SQL，不勾选仅生成SQL</span>
                </div>
                <button class="ward-submit-btn" type="button">确认执行</button>
                <div class="ward-result" style="display:none"></div>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // 阻止表单内点击冒泡到 overlay 导致误关
        dialog.addEventListener('click', (e) => e.stopPropagation());
        // 点击遮罩关闭
        overlay.addEventListener('click', () => overlay.remove());
        // 关闭按钮
        dialog.querySelector('.ward-dialog-close').addEventListener('click', () => overlay.remove());

        // 提交
        dialog.querySelector('.ward-submit-btn').addEventListener('click', async () => {
            const getVal = (n) => dialog.querySelector(`input[name="${n}"]`).value.trim();

            const host = getVal('dbHost');
            if (!host) { showToast('❌ 请输入数据库地址', 'error'); return; }

            const requestData = {
                dbHost: host,
                dbPort: getVal('dbPort'),
                dbName: getVal('dbName'),
                username: getVal('username'),
                password: getVal('password'),
                sqlType: sqlType,
                directExecution: dialog.querySelector('input[name="directExecution"]').checked
            };
            requestData[field.name] = getVal('opValue');

            const btn = dialog.querySelector('.ward-submit-btn');
            const resultDiv = dialog.querySelector('.ward-result');

            btn.disabled = true;
            btn.textContent = '⏳ 处理中...';
            resultDiv.style.display = 'block';
            resultDiv.textContent = '正在请求...';
            resultDiv.className = 'ward-result ward-result-info';

            try {
                const response = await fetch(apiUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestData)
                });
                const res = await response.json();
                if (res.status === 'error') {
                    resultDiv.textContent = '❌ ' + (res.message || '操作失败');
                    resultDiv.className = 'ward-result ward-result-error';
                } else {
                    resultDiv.textContent = '✅ ' + (res.message || '操作成功');
                    resultDiv.className = 'ward-result ward-result-success';
                }
            } catch (e) {
                resultDiv.textContent = '❌ 请求失败: ' + e.message;
                resultDiv.className = 'ward-result ward-result-error';
            }

            btn.disabled = false;
            btn.textContent = '确认执行';
        });
    }

    // ==============================
    // 上传 localStorage 弹窗
    // ==============================
    function showUploadDialog(apiBaseUrl) {
        const existing = document.getElementById('ward-dialog-overlay');
        if (existing) existing.remove();

        // 读取当前页面 localStorage
        let lsData = {};
        try {
            for (let i = 0; i < window.localStorage.length; i++) {
                const key = window.localStorage.key(i);
                lsData[key] = window.localStorage.getItem(key);
            }
        } catch (e) {
            console.error('[Ward] 读取 localStorage 失败:', e);
        }

        const overlay = document.createElement('div');
        overlay.id = 'ward-dialog-overlay';
        const dialog = document.createElement('div');
        dialog.className = 'ward-dialog';

        const keyCount = Object.keys(lsData).length;
        const preview = JSON.stringify(lsData, null, 2);
        const previewText = preview.length > 2000 ? preview.substring(0, 2000) + '\n... (内容过长已截断)' : preview;

        dialog.innerHTML = `
            <div class="ward-dialog-header">
                <span>📤 上传 localStorage 数据</span>
                <span class="ward-dialog-close">&times;</span>
            </div>
            <div class="ward-dialog-body">
                <div class="ward-form-group">
                    <label>请求地址</label>
                    <input type="text" name="uploadUrl" value="${apiBaseUrl}/upload-localstorage" placeholder="完整请求地址">
                </div>
                <div class="ward-form-group">
                    <label>当前页面 localStorage（共 ${keyCount} 项）</label>
                    <textarea name="lsData" rows="10" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;font-size:12px;font-family:monospace;resize:vertical"></textarea>
                    <p class="ward-hint">可在上方编辑后提交，数据将以 JSON 格式 POST 到上方地址</p>
                </div>
                <button class="ward-submit-btn" type="button">确认上传</button>
                <div class="ward-result" style="display:none"></div>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
        // 通过 DOM 属性赋值，避免模板字面量转义问题
        dialog.querySelector('textarea[name="lsData"]').value = previewText;

        dialog.addEventListener('click', (e) => e.stopPropagation());
        overlay.addEventListener('click', () => overlay.remove());
        dialog.querySelector('.ward-dialog-close').addEventListener('click', () => overlay.remove());

        dialog.querySelector('.ward-submit-btn').addEventListener('click', async () => {
            const uploadUrl = dialog.querySelector('input[name="uploadUrl"]').value.trim();
            if (!uploadUrl) { showToast('❌ 请输入请求地址', 'error'); return; }

            let payload;
            try {
                payload = JSON.parse(dialog.querySelector('textarea[name="lsData"]').value);
            } catch (e) {
                showToast('❌ JSON 格式错误: ' + e.message, 'error');
                return;
            }

            const btn = dialog.querySelector('.ward-submit-btn');
            const resultDiv = dialog.querySelector('.ward-result');
            btn.disabled = true;
            btn.textContent = '⏳ 上传中...';
            resultDiv.style.display = 'block';
            resultDiv.textContent = '正在请求...';
            resultDiv.className = 'ward-result ward-result-info';

            try {
                const response = await fetch(uploadUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        pageUrl: window.location.href,
                        pageHost: url.hostname,
                        data: payload
                    })
                });
                const res = await response.json();
                if (res.status === 'error') {
                    resultDiv.textContent = '❌ ' + (res.message || '上传失败');
                    resultDiv.className = 'ward-result ward-result-error';
                } else {
                    resultDiv.textContent = '✅ ' + (res.message || '上传成功');
                    resultDiv.className = 'ward-result ward-result-success';
                }
            } catch (e) {
                resultDiv.textContent = '❌ 请求失败: ' + e.message;
                resultDiv.className = 'ward-result ward-result-error';
            }

            btn.disabled = false;
            btn.textContent = '确认上传';
        });
    }

    // ==============================
    // 批量创建设备弹窗
    // ==============================
    function showDeviceDialog(apiBaseUrl) {
        const existing = document.getElementById('ward-dialog-overlay');
        if (existing) existing.remove();

        const serverIp = url.hostname;

        // 从 localStorage 获取 orgId
        let orgId = '';
        try {
            const orgInfoStr = window.localStorage.getItem('orgInfo');
            if (orgInfoStr) {
                const orgInfo = JSON.parse(orgInfoStr);
                orgId = orgInfo.orgId || '';
            }
        } catch (e) { console.warn('[Ward] 解析 orgInfo 失败:', e); }

        // 设备类型映射
        const deviceTypes = [
            { value: 'wnBedHeadExtension', label: '🛏️ 床头分机' },
            { value: 'wnBedSideExtension', label: '🖥️ 床旁分机' },
            { value: 'wnToiletExtension', label: '🚻 卫生间分机' },
            { value: 'wnDutyMainframe', label: '🖥️ 值班室主机' },
            { value: 'wnDoorWayExtension', label: '🚪 门口分机' },
            { value: 'wnEntranceGuard', label: '🔐 门禁分机' },
            { value: 'wnMedicalMainframe', label: '🏥 医护主机' },
            { value: 'rvKinVisitExtension', label: '👋 探视分机' },
            { value: 'wnMedicalAudioAssistant', label: '📱 手持设备' },
            { value: 'wnDoorLampExtension', label: '💡 门灯' },
            { value: 'wnCorridorScreen', label: '📺 走廊显示屏' },
            { value: 'wnCorridorLatticeScreen', label: '📟 走廊点阵屏' },
            { value: 'bnNursingTV', label: '📟 智能护理看板' }
        ];
        const deviceTypeNameMap = {
            wnBedHeadExtension: '床头分机', wnBedSideExtension: '床旁分机',
            wnToiletExtension: '卫生间分机', wnDutyMainframe: '值班室主机',
            wnDoorWayExtension: '门口分机', wnEntranceGuard: '门禁分机',
            wnMedicalMainframe: '医护主机', rvKinVisitExtension: '探视分机',
            wnMedicalAudioAssistant: '手持设备', wnDoorLampExtension: '门灯',
            wnCorridorScreen: '走廊显示屏', wnCorridorLatticeScreen: '走廊点阵屏',
            bnNursingTV: '智能护理看板'
        };

        const defaultVersions = JSON.stringify({
            "appVersion": "3.4.2.004-20260327",
            "authVersion": "1.2.5",
            "callVersion": "1.61.0.17-alpha163",
            "upbsVersion": "3.4.0.004-20251017",
            "systemVersion": "rk3566_rgo-userdebug 11 RQ2A.210505.003 eng.yarwar.20230908.222902 release-keys",
            "hardwareVersion": "无硬件版本信息 - 4C:31:2D:2B:32:0B"
        }, null, 2);
        const defaultParams = JSON.stringify({ "rotate": "0", "volume": "6", "brighter": "0", "resolution": "1024*600" }, null, 2);
        const defaultPositions = JSON.stringify({ "bedId": "", "roomId": "", "roomIdList": [], "positionStr": null, "InstallationRoomId": "" }, null, 2);

        const overlay = document.createElement('div');
        overlay.id = 'ward-dialog-overlay';
        const dialog = document.createElement('div');
        dialog.className = 'ward-dialog ward-device-dialog';

        // 设备类型 option HTML
        const deviceTypeOptions = deviceTypes.map(d =>
            `<option value="${d.value}">${d.label} (${d.value})</option>`
        ).join('');

        dialog.innerHTML = `
            <div class="ward-dialog-header">
                <span>📦 批量创建设备</span>
                <span class="ward-dialog-close">&times;</span>
            </div>
            <div class="ward-dialog-body ward-device-body">
                <div class="ward-section-title">服务器配置</div>
                <div class="ward-form-row">
                    <div class="ward-form-group"><label>服务器IP</label><input type="text" name="serverIp" value="${serverIp}"></div>
                    <div class="ward-form-group"><label>端口号</label><input type="text" name="port" value="80"></div>
                    <div class="ward-form-group"><label>上下文路径</label><input type="text" name="contextPath" value="/tdms"></div>
                </div>
                <div class="ward-section-title">设备配置</div>
                <div class="ward-form-row">
                    <div class="ward-form-group"><label>机构ID</label><div style="display:flex;gap:6px;align-items:center"><input type="text" name="orgId" value="${orgId}" placeholder="从 localStorage 自动获取" style="flex:1"><button type="button" class="ward-fetch-org-btn" style="white-space:nowrap;padding:4px 10px;font-size:12px">获取</button></div><span class="ward-hint" id="ward-org-status">${orgId ? '✅ 已从 localStorage 获取' : '⚠️ 未获取到，可点击获取或手动填写'}</span></div>
                    <div class="ward-form-group"><label>科室ID（可选）</label><input type="text" name="deptId" placeholder="可选"></div>
                </div>
                <div class="ward-form-row">
                    <div class="ward-form-group"><label>设备类型</label><select name="deviceType">${deviceTypeOptions}</select></div>
                    <div class="ward-form-group"><label>接口版本</label><div class="ward-radio-group"><label><input type="radio" name="apiVersion" value="old" checked> 老接口</label><label><input type="radio" name="apiVersion" value="new"> 新接口</label></div></div>
                </div>
                <div class="ward-form-row">
                    <div class="ward-form-group"><label>设备数量</label><input type="number" name="deviceCount" value="10" min="1" max="100"></div>
                    <div class="ward-form-group"><label>起始设备号</label><input type="text" name="startDeviceNum" value="BED001"></div>
                    <div class="ward-form-group"><label>起始IP地址</label><input type="text" name="startIp" value="192.168.31.201"></div>
                </div>
                <div class="ward-section-title">设备型号</div>
                <div class="ward-form-group"><label>设备型号</label><select name="deviceModel"><option value="A10">A10</option><option value="A27L">A27L</option><option value="A36">A36</option><option value="A25">A25</option></select></div>
                <div class="ward-section-title ward-advanced-toggle">▶ 高级配置（点击展开）</div>
                <div class="ward-advanced-content" style="display:none">
                    <div class="ward-form-row">
                        <div class="ward-form-group"><label>房间ID模板</label><input type="text" name="roomIdTemplate" placeholder="留空则不设置，如: room{index}"></div>
                        <div class="ward-form-group"><label>床位ID模板</label><input type="text" name="bedIdTemplate" placeholder="留空则不设置，如: bed{index}"></div>
                    </div>
                    <div class="ward-form-row">
                        <div class="ward-form-group"><label>MAC地址前缀</label><input type="text" name="macPrefix" value="AA:BB:CC:DD:EE"></div>
                        <div class="ward-form-group"><label>设备名称前缀</label><input type="text" name="deviceNamePrefix" value="床旁分机"></div>
                    </div>
                    <div class="ward-form-group"><label>Versions JSON</label><textarea name="versionsJson" rows="4" class="ward-mono"></textarea></div>
                    <div class="ward-form-group"><label>Params JSON</label><textarea name="paramsJson" rows="3" class="ward-mono"></textarea></div>
                    <div class="ward-form-group"><label>Positions JSON</label><textarea name="positionsJson" rows="3" class="ward-mono"></textarea></div>
                </div>
                <button class="ward-submit-btn" type="button">🚀 开始添加设备</button>
                <div class="ward-device-progress" style="display:none">
                    <div class="ward-progress-bar"><div class="ward-progress-fill"></div></div>
                    <div class="ward-progress-text"></div>
                </div>
                <div class="ward-device-results" style="display:none"></div>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // 通过 DOM 赋值 JSON 内容
        dialog.querySelector('textarea[name="versionsJson"]').value = defaultVersions;
        dialog.querySelector('textarea[name="paramsJson"]').value = defaultParams;
        dialog.querySelector('textarea[name="positionsJson"]').value = defaultPositions;

        // 设备类型切换时更新名称前缀
        const deviceTypeSelect = dialog.querySelector('select[name="deviceType"]');
        const namePrefixInput = dialog.querySelector('input[name="deviceNamePrefix"]');
        deviceTypeSelect.addEventListener('change', () => {
            const name = deviceTypeNameMap[deviceTypeSelect.value];
            if (name) namePrefixInput.value = name;
        });

        // 高级配置展开/收起
        const advToggle = dialog.querySelector('.ward-advanced-toggle');
        const advContent = dialog.querySelector('.ward-advanced-content');
        advToggle.addEventListener('click', () => {
            const hidden = advContent.style.display === 'none';
            advContent.style.display = hidden ? 'block' : 'none';
            advToggle.textContent = hidden ? '▼ 高级配置（点击收起）' : '▶ 高级配置（点击展开）';
        });

        // 获取机构列表（fallback）
        async function fetchOrgId() {
            const ip = dialog.querySelector('input[name="serverIp"]').value.trim();
            if (!ip) { showToast('❌ 请先输入服务器IP', 'error'); return; }
            const statusEl = dialog.querySelector('#ward-org-status');
            statusEl.textContent = '⏳ 正在获取...';
            try {
                const resp = await fetch(apiBaseUrl + '/api/v1/orgs/getOrgs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ serverIp: ip })
                });
                const res = await resp.json();
                if (res.status === 200 && res.data && res.data.length > 0) {
                    dialog.querySelector('input[name="orgId"]').value = res.data[0].orgId;
                    statusEl.textContent = `✅ 获取到 ${res.data.length} 个机构，已填入第一个`;
                } else {
                    statusEl.textContent = '⚠️ 未获取到机构信息，请手动填写';
                }
            } catch (e) {
                statusEl.textContent = '❌ 获取失败: ' + e.message;
            }
        }

        // 关闭逻辑
        dialog.addEventListener('click', (e) => e.stopPropagation());
        overlay.addEventListener('click', () => overlay.remove());
        dialog.querySelector('.ward-dialog-close').addEventListener('click', () => overlay.remove());
        dialog.querySelector('.ward-fetch-org-btn').addEventListener('click', () => fetchOrgId());

        // ===== 辅助函数 =====
        function generateUUID() {
            return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
            });
        }
        function generateDeviceAppId() {
            const chars = '0123456789abcdef';
            let result = '';
            for (let i = 0; i < 16; i++) result += chars[Math.floor(Math.random() * chars.length)];
            return result;
        }
        function parseNumber(str) {
            const match = str.match(/\d+$/);
            return match ? parseInt(match[0]) : 0;
        }
        function generateDeviceNum(startDeviceNum, index) {
            const baseNum = parseNumber(startDeviceNum);
            const prefix = startDeviceNum.replace(/\d+$/, '');
            return prefix + String(baseNum + index).padStart(3, '0');
        }
        function generateIp(startIp, index) {
            const parts = startIp.split('.').map(Number);
            const last = parts[3] + index;
            if (last > 254) return null;
            return `${parts[0]}.${parts[1]}.${parts[2]}.${last}`;
        }
        function generateMac(macPrefix, index) {
            return `${macPrefix}:${String(index).padStart(2, '0').toUpperCase()}`;
        }
        function generateDeviceName(namePrefix, index) {
            return `${namePrefix}${String(index + 1).padStart(3, '0')}`;
        }
        function replaceTemplate(template, index) {
            if (!template) return '';
            return template.replace('{index}', String(index + 1).padStart(3, '0'));
        }
        function buildRequestData(formData, index) {
            const deviceId = generateUUID();
            const deviceNum = generateDeviceNum(formData.startDeviceNum, index);
            const ip = generateIp(formData.startIp, index);
            if (!ip) throw new Error('IP地址超出范围');

            const data = {
                ip: ip,
                deviceName: generateDeviceName(formData.deviceNamePrefix, index),
                deviceNum: deviceNum,
                deviceAppId: generateDeviceAppId(),
                deviceType: formData.deviceType,
                orgId: formData.orgId,
                deviceModel: formData.deviceModel,
                mac: generateMac(formData.macPrefix, index)
            };
            if (formData.apiVersion === 'new') data.deviceId = deviceId;
            if (formData.deptId) data.deptId = formData.deptId;

            try {
                if (formData.versionsJson) data.versions = formData.versionsJson;
                if (formData.paramsJson) data.params = formData.paramsJson;
                if (formData.positionsJson) {
                    let positions = JSON.parse(formData.positionsJson);
                    positions.roomId = replaceTemplate(formData.roomIdTemplate, index);
                    positions.bedId = replaceTemplate(formData.bedIdTemplate, index);
                    data.positions = JSON.stringify(positions);
                }
            } catch (e) { console.error('[Ward] JSON解析错误:', e); }
            return data;
        }

        // ===== 提交 =====
        dialog.querySelector('.ward-submit-btn').addEventListener('click', async () => {
            const getVal = (n) => dialog.querySelector(`[name="${n}"]`).value.trim();
            const formData = {
                serverIp: getVal('serverIp'),
                port: getVal('port'),
                contextPath: getVal('contextPath'),
                orgId: getVal('orgId'),
                deptId: getVal('deptId'),
                deviceType: getVal('deviceType'),
                apiVersion: dialog.querySelector('input[name="apiVersion"]:checked').value,
                deviceCount: parseInt(getVal('deviceCount')) || 10,
                startDeviceNum: getVal('startDeviceNum'),
                startIp: getVal('startIp'),
                deviceModel: getVal('deviceModel'),
                roomIdTemplate: getVal('roomIdTemplate'),
                bedIdTemplate: getVal('bedIdTemplate'),
                macPrefix: getVal('macPrefix'),
                deviceNamePrefix: getVal('deviceNamePrefix'),
                versionsJson: dialog.querySelector('textarea[name="versionsJson"]').value,
                paramsJson: dialog.querySelector('textarea[name="paramsJson"]').value,
                positionsJson: dialog.querySelector('textarea[name="positionsJson"]').value
            };

            if (!formData.serverIp) { showToast('❌ 请输入服务器IP', 'error'); return; }
            if (!formData.orgId) { showToast('❌ 请输入机构ID', 'error'); return; }
            if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(formData.startIp)) { showToast('❌ 起始IP格式不正确', 'error'); return; }

            const btn = dialog.querySelector('.ward-submit-btn');
            const progressDiv = dialog.querySelector('.ward-device-progress');
            const resultsDiv = dialog.querySelector('.ward-device-results');
            const progressFill = progressDiv.querySelector('.ward-progress-fill');
            const progressText = progressDiv.querySelector('.ward-progress-text');

            btn.disabled = true;
            btn.textContent = '⏳ 处理中...';
            progressDiv.style.display = 'block';
            resultsDiv.style.display = 'block';
            resultsDiv.innerHTML = '';

            const total = formData.deviceCount;
            const createUrl = apiBaseUrl + '/api/v1/device-proxy/create';
            let successCount = 0;

            for (let i = 0; i < total; i++) {
                const pct = Math.round((i / total) * 100);
                progressFill.style.width = pct + '%';
                progressText.textContent = `正在处理: ${i + 1} / ${total}`;

                let result;
                try {
                    const reqData = buildRequestData(formData, i);
                    const fullData = { ...reqData, serverIp: formData.serverIp, port: formData.port, contextPath: formData.contextPath, apiVersion: formData.apiVersion };
                    const resp = await fetch(createUrl, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(fullData)
                    });
                    const res = await resp.json();
                    if (res.status === 200) {
                        result = { success: true, index: i + 1, message: res.desc || '添加成功', deviceId: res.data?.deviceId };
                        successCount++;
                    } else {
                        result = { success: false, index: i + 1, message: res.desc || `失败(status:${res.status})` };
                    }
                } catch (e) {
                    result = { success: false, index: i + 1, message: '❌ ' + e.message };
                }

                const item = document.createElement('div');
                item.className = 'ward-result-item ' + (result.success ? 'ward-result-success' : 'ward-result-error');
                item.textContent = `${result.success ? '✅' : '❌'} 设备${result.index}: ${result.message}${result.deviceId ? ' (ID:' + result.deviceId + ')' : ''}`;
                resultsDiv.appendChild(item);
                resultsDiv.scrollTop = resultsDiv.scrollHeight;

                if (i < total - 1) await new Promise(r => setTimeout(r, 300));
            }

            progressFill.style.width = '100%';
            progressText.textContent = `完成！成功: ${successCount}, 失败: ${total - successCount}`;
            btn.disabled = false;
            btn.textContent = '🚀 开始添加设备';
            showToast(`✅ 批量创建完成: 成功${successCount}, 失败${total - successCount}`);
        });
    }

    // ===== 异步初始化 =====
    async function init() {
        const config = await ConfigManager.getConfig();
        // 纯数字IP + 80端口（默认HTTP端口，url.port为空）自动加载
        const isDefaultIP = isNumericIP(url.hostname) && (url.port === '' || url.port === '80');
        if (!isDefaultIP) return;
        createFloatingMenu(config);
    }

    // ==============================
    // 加载自定义按钮图片
    // ==============================
    function applyButtonImages(toggleBtn, config) {
        const collapsedUrl = config.btnImageCollapsed;
        const expandedUrl = config.btnImageExpanded;
        if (!collapsedUrl && !expandedUrl) return;

        if (collapsedUrl) {
            const img = new Image();
            img.onload = () => {
                toggleBtn.style.backgroundImage = `url("${collapsedUrl}")`;
                toggleBtn.style.backgroundSize = 'cover';
                toggleBtn.style.backgroundPosition = 'center';
                toggleBtn.textContent = '';
                toggleBtn.classList.add('has-custom-image');
            };
            img.onerror = () => {
                console.warn('[Ward] 收缩态图片加载失败:', collapsedUrl);
            };
            img.src = collapsedUrl;
        }

        if (expandedUrl) {
            const img = new Image();
            img.onload = () => {
                toggleBtn.dataset.expandedImageUrl = expandedUrl;
            };
            img.onerror = () => {
                console.warn('[Ward] 展开态图片加载失败:', expandedUrl);
                toggleBtn.dataset.expandedImageUrl = '';
            };
            img.src = expandedUrl;
        }

        const observer = new MutationObserver(() => {
            const isExpanded = toggleBtn.classList.contains('expanded');
            if (isExpanded && toggleBtn.dataset.expandedImageUrl) {
                toggleBtn.style.backgroundImage = `url("${toggleBtn.dataset.expandedImageUrl}")`;
            } else if (!isExpanded && collapsedUrl) {
                toggleBtn.style.backgroundImage = `url("${collapsedUrl}")`;
            }
        });
        observer.observe(toggleBtn, { attributes: true, attributeFilter: ['class'] });
    }

    // ==============================
    // 浮动菜单
    // ==============================
    function createFloatingMenu(config) {
        const container = document.createElement('div');
        container.id = 'tple-float-menu';

        const toggleBtn = document.createElement('div');
        toggleBtn.id = 'tple-toggle-btn';
        toggleBtn.textContent = '+';
        toggleBtn.title = '病房开发辅助';

        applyButtonImages(toggleBtn, config);

        const apiBaseUrl = config.apiBaseUrl || 'http://192.168.18.228:28019';

        const menuItems = [
            { text: '👤 添加用户', action: () => showOperationDialog('insertUser', '添加用户', apiBaseUrl) },
            { text: '🗑️ 删除某IP占用的设备', action: () => showOperationDialog('deleteip', '删除某IP占用的设备', apiBaseUrl) },
            { text: '📂 添加护理标签分类', action: () => showOperationDialog('addlabelclass', '添加护理标签分类', apiBaseUrl) },
            { text: '🏷️ 添加护理标签（每分类）', action: () => showOperationDialog('addlabel', '添加护理标签【每个分类下面都添加】', apiBaseUrl) },
            { text: '📤 上传 localStorage', action: () => showUploadDialog(apiBaseUrl) },
            { text: '📦 批量创建设备', action: () => showDeviceDialog(apiBaseUrl) }
        ];

        const itemEls = [];
        menuItems.forEach((item) => {
            const el = document.createElement('div');
            el.className = 'tple-menu-item';
            el.textContent = item.text;
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault();
                if (hasMoved) return;
                try { item.action(); } catch (err) { console.error('[Ward] 菜单动作执行失败:', err); }
                closeMenu();
            });
            container.appendChild(el);
            itemEls.push(el);
        });

        container.appendChild(toggleBtn);

        let menuOpen = false;
        let autoCollapseTimer = null;

        function closeMenu() {
            menuOpen = false;
            toggleBtn.classList.remove('expanded');
            itemEls.forEach(ie => ie.classList.remove('visible'));
            if (autoCollapseTimer) { clearTimeout(autoCollapseTimer); autoCollapseTimer = null; }
        }

        function startAutoCollapse() {
            if (autoCollapseTimer) clearTimeout(autoCollapseTimer);
            const timeout = parseInt(config.autoCollapseTimeout) || 0;
            if (timeout > 0) {
                autoCollapseTimer = setTimeout(() => {
                    if (menuOpen) closeMenu();
                }, timeout * 1000);
            }
        }

        toggleBtn.addEventListener('click', () => {
            if (hasMoved) return;
            menuOpen = !menuOpen;
            toggleBtn.classList.toggle('expanded', menuOpen);
            itemEls.forEach((el, i) => {
                if (menuOpen) {
                    setTimeout(() => el.classList.add('visible'), i * 50);
                } else {
                    el.classList.remove('visible');
                }
            });
            if (menuOpen) startAutoCollapse();
            else if (autoCollapseTimer) { clearTimeout(autoCollapseTimer); autoCollapseTimer = null; }
        });

        // 拖拽功能
        let isDragging = false;
        let startX, startY, initialLeft, initialTop;
        let hasMoved = false;

        function clampPosition(left, top) {
            const btnW = container.offsetWidth;
            const btnH = container.offsetHeight;
            const maxLeft = window.innerWidth - btnW;
            const maxTop = window.innerHeight - btnH;
            return {
                left: Math.max(0, Math.min(left, maxLeft)),
                top: Math.max(0, Math.min(top, maxTop))
            };
        }

        function onDragStart(e) {
            if (e.button !== 0) return;
            isDragging = true;
            hasMoved = false;
            startX = e.clientX;
            startY = e.clientY;
            const rect = container.getBoundingClientRect();
            initialLeft = rect.left;
            initialTop = rect.top;
            toggleBtn.classList.add('dragging');
            if (menuOpen) closeMenu();
            e.preventDefault();
        }

        function onDragMove(e) {
            if (!isDragging) return;
            const deltaX = e.clientX - startX;
            const deltaY = e.clientY - startY;
            if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) hasMoved = true;
            const pos = clampPosition(initialLeft + deltaX, initialTop + deltaY);
            container.style.right = 'auto';
            container.style.bottom = 'auto';
            container.style.left = pos.left + 'px';
            container.style.top = pos.top + 'px';
        }

        function onDragEnd() {
            if (!isDragging) return;
            isDragging = false;
            toggleBtn.classList.remove('dragging');
        }

        toggleBtn.addEventListener('mousedown', onDragStart);
        window.addEventListener('mousemove', onDragMove);
        window.addEventListener('mouseup', onDragEnd);
        window.addEventListener('mouseleave', onDragEnd);

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => document.body.appendChild(container));
        } else {
            document.body.appendChild(container);
        }
    }

    // ===== 启动 =====
    init();
})();
