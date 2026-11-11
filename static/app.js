let currentScanItems = [];
let scanStats = null;
let currentMode = "copy";
let ws = null;

// DOM Elements
const inputSource = document.getElementById('input-source-dir');
const inputOutput = document.getElementById('input-output-dir');
const btnBrowseSource = document.getElementById('btn-browse-source');
const btnBrowseOutput = document.getElementById('btn-browse-output');
const btnModeCopy = document.getElementById('btn-mode-copy');
const btnModeMove = document.getElementById('btn-mode-move');
const chkExif = document.getElementById('chk-exif');
const chkMagic = document.getElementById('chk-magic');
const chkLivephoto = document.getElementById('chk-livephoto');
const btnScan = document.getElementById('btn-scan');
const btnStart = document.getElementById('btn-start');
const btnCancel = document.getElementById('btn-cancel');
const exifBadge = document.getElementById('exiftool-badge');

const statMedia = document.getElementById('stat-media');
const statTotal = document.getElementById('stat-total');
const statMatched = document.getElementById('stat-matched');
const statMatchedSub = document.getElementById('stat-matched-sub');
const statLive = document.getElementById('stat-live');
const statRepaired = document.getElementById('stat-repaired');

const progressLabel = document.getElementById('progress-label');
const progressPercentage = document.getElementById('progress-percentage');
const progressBar = document.getElementById('progress-bar');
const progressCounts = document.getElementById('progress-counts');
const progressStatus = document.getElementById('progress-status');
const spinner = document.getElementById('spinner');

const folderPreview = document.getElementById('folder-preview');
const logConsole = document.getElementById('log-console');
const btnClearLog = document.getElementById('btn-clear-log');

// Logging
function appendLog(text, type = "info") {
    const time = new Date().toLocaleTimeString();
    const div = document.createElement('div');
    div.className = "flex items-start gap-2 text-[11px] leading-relaxed";
    
    let colorClass = "text-slate-300";
    if (type === "success") colorClass = "text-emerald-400";
    if (type === "warn") colorClass = "text-amber-400";
    if (type === "error") colorClass = "text-rose-400";
    if (type === "system") colorClass = "text-indigo-400";

    div.innerHTML = `<span class="text-slate-600 select-none">[${time}]</span> <span class="${colorClass}">${text}</span>`;
    logConsole.appendChild(div);
    logConsole.scrollTop = logConsole.scrollHeight;
}

btnClearLog.addEventListener('click', () => {
    logConsole.innerHTML = '';
});

// Folder Browse Handlers
async function browseFolder(initialPath) {
    try {
        const res = await fetch('/api/browse-folder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ initial: initialPath })
        });
        if (res.ok) {
            const data = await res.json();
            return data.folder || null;
        }
    } catch (e) {
        console.error('폴더 선택 창 호출 에러:', e);
    }
    return null;
}

btnBrowseSource.addEventListener('click', async () => {
    btnBrowseSource.disabled = true;
    const selected = await browseFolder(inputSource.value);
    btnBrowseSource.disabled = false;
    if (selected) {
        inputSource.value = selected;
    }
});

btnBrowseOutput.addEventListener('click', async () => {
    btnBrowseOutput.disabled = true;
    const selected = await browseFolder(inputOutput.value);
    btnBrowseOutput.disabled = false;
    if (selected) {
        inputOutput.value = selected;
    }
});

// Mode Toggle
btnModeCopy.addEventListener('click', () => {
    currentMode = "copy";
    btnModeCopy.className = "text-xs px-2.5 py-1 rounded-md font-medium transition bg-indigo-600 text-white shadow";
    btnModeMove.className = "text-xs px-2.5 py-1 rounded-md font-medium transition text-slate-400 hover:text-slate-200";
});

btnModeMove.addEventListener('click', () => {
    currentMode = "move";
    btnModeMove.className = "text-xs px-2.5 py-1 rounded-md font-medium transition bg-rose-600 text-white shadow";
    btnModeCopy.className = "text-xs px-2.5 py-1 rounded-md font-medium transition text-slate-400 hover:text-slate-200";
});

// Check Exiftool Status
async function checkExifTool() {
    try {
        const res = await fetch('/api/exiftool-status');
        const data = await res.json();
        if (data.available) {
            exifBadge.innerHTML = `
                <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
                <span class="text-emerald-400 font-medium">ExifTool v${data.version || 'OK'}</span>
            `;
        } else {
            exifBadge.innerHTML = `
                <span class="w-2 h-2 rounded-full bg-amber-400"></span>
                <span class="text-amber-400 font-medium">ExifTool 미설치 (시간만 동기화)</span>
            `;
        }
        if (data.default_source) {
            inputSource.value = data.default_source;
        }
        if (data.default_output) {
            inputOutput.value = data.default_output;
        }
    } catch (e) {
        console.error(e);
    }
}

// Render Monthly Folder Distribution
function updateFolderPreview(items) {
    folderPreview.innerHTML = '';
    const months = {};
    for (const item of items) {
        const m = item.target_month || 'Unknown';
        months[m] = (months[m] || 0) + 1;
    }

    const sortedMonths = Object.keys(months).sort();
    if (sortedMonths.length === 0) {
        folderPreview.innerHTML = `<div class="col-span-full py-6 text-center text-xs text-slate-500">분류 가능한 항목이 없습니다.</div>`;
        return;
    }

    for (const m of sortedMonths) {
        const card = document.createElement('div');
        card.className = "bg-slate-900/90 border border-slate-700/60 rounded-xl p-2.5 text-center flex flex-col justify-center items-center hover:border-indigo-500/50 transition";
        card.innerHTML = `
            <span class="text-xs font-mono font-semibold text-indigo-300">${m}</span>
            <span class="text-[11px] text-slate-400 mt-1 font-mono">${months[m].toLocaleString()}장</span>
        `;
        folderPreview.appendChild(card);
    }
}

// Scan Action
btnScan.addEventListener('click', async () => {
    const sourceDir = inputSource.value.trim();
    if (!sourceDir) {
        alert("원본 폴더 경로를 입력하세요.");
        return;
    }

    btnScan.disabled = true;
    btnScan.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>스캔 분석 중...</span>`;
    spinner.classList.remove('hidden');
    progressLabel.innerText = "폴더 스캔 및 메타데이터 매칭 분석 중...";
    appendLog(`[스캔 시작] '${sourceDir}' 경로 탐색 중...`, 'system');

    try {
        const res = await fetch('/api/scan', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ source_dir: sourceDir })
        });
        const data = await res.json();
        if (data.error) {
            appendLog(`[스캔 오류] ${data.error}`, 'error');
            alert(data.error);
            return;
        }

        currentScanItems = data.items;
        scanStats = data.stats;

        // Update Stats UI
        statMedia.innerText = scanStats.media_files.toLocaleString();
        statTotal.innerText = `전체 ${scanStats.total_files.toLocaleString()}개 중`;
        
        const matchPct = scanStats.media_files > 0 ? Math.round((scanStats.matched_json / scanStats.media_files) * 100) : 0;
        statMatched.innerText = `${matchPct}%`;
        statMatchedSub.innerText = `${scanStats.matched_json.toLocaleString()}개 메타 매칭`;

        statLive.innerText = scanStats.live_photos.toLocaleString();
        statRepaired.innerText = scanStats.extension_fixed.toLocaleString();

        updateFolderPreview(currentScanItems);

        appendLog(`[스캔 완료] 미디어 ${scanStats.media_files}개 발견 (JSON 매칭: ${scanStats.matched_json}개, 라이브포토: ${scanStats.live_photos}개)`, 'success');
        progressLabel.innerText = "스캔 완료 - 정리 대기 중";
        btnStart.disabled = false;

    } catch (e) {
        appendLog(`[스캔 통신 실패] ${e.message}`, 'error');
    } finally {
        btnScan.disabled = false;
        btnScan.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i> <span>폴더 재분석 (Scan)</span>`;
        spinner.classList.add('hidden');
    }
});

// Realtime Progress Tracker (Polling fallback + WebSocket)
let progressInterval = null;

function handleProgressData(data) {
    if (data.event === "progress") {
        const item = data.item;
        const stats = data.stats;
        progressBar.style.width = `${stats.percent}%`;
        progressPercentage.innerText = `${stats.percent}%`;
        progressCounts.innerText = `처리: ${stats.processed} / ${stats.total} (성공: ${stats.success}, 실패: ${stats.failed})`;
        progressStatus.innerText = item.filename;

        if (stats.processed % 5 === 0 || item.status === 'error' || stats.processed === 1) {
            const logType = item.status === 'error' ? 'error' : 'info';
            appendLog(`[${stats.processed}/${stats.total}] ${item.filename} -> ${item.status}`, logType);
        }
    } else if (data.event === "done") {
        if (progressInterval) clearInterval(progressInterval);
        progressBar.style.width = `100%`;
        progressPercentage.innerText = `100%`;
        progressLabel.innerText = "작업 완료!";
        spinner.classList.add('hidden');
        appendLog(`[작업 종료] 총 ${data.stats.total}개 중 ${data.stats.success}개 성공 처리 완료.`, 'success');
        btnStart.disabled = false;
        btnScan.disabled = false;
        btnCancel.classList.add('hidden');
    } else if (data.event === "cancelled") {
        if (progressInterval) clearInterval(progressInterval);
        progressLabel.innerText = "작업 중단됨";
        spinner.classList.add('hidden');
        appendLog(`[작업 중단] 사용자가 작업을 취소했습니다.`, 'warn');
        btnStart.disabled = false;
        btnScan.disabled = false;
        btnCancel.classList.add('hidden');
    }
}

function startProgressPolling() {
    if (progressInterval) clearInterval(progressInterval);
    progressInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/progress');
            if (res.ok) {
                const data = await res.json();
                handleProgressData(data);
            }
        } catch (e) {
            console.error(e);
        }
    }, 400);
}

// Start Organize
btnStart.addEventListener('click', async () => {
    const outputDir = inputOutput.value.trim();
    if (!outputDir) {
        alert("정리된 파일을 저장할 폴더 경로를 입력하세요.");
        return;
    }

    if (!confirm(`선택한 모드: [${currentMode.toUpperCase()}]\n총 ${currentScanItems.length}개의 파일을 정리하시겠습니까?`)) {
        return;
    }

    btnStart.disabled = true;
    btnScan.disabled = true;
    btnCancel.classList.remove('hidden');
    spinner.classList.remove('hidden');
    progressLabel.innerText = "정리 및 메타데이터 주입 진행 중...";

    appendLog(`[작업 시작] 모드: ${currentMode}, 대상 폴더: ${outputDir}`, 'system');

    try {
        const res = await fetch('/api/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                output_dir: outputDir,
                action: currentMode,
                write_exif: chkExif.checked
            })
        });
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            btnStart.disabled = false;
            btnScan.disabled = false;
            btnCancel.classList.add('hidden');
            spinner.classList.add('hidden');
            return;
        }

        // Start reliable polling loop
        startProgressPolling();

    } catch (e) {
        appendLog(`[작업 시작 실패] ${e.message}`, 'error');
    }
});

// Cancel Job
btnCancel.addEventListener('click', async () => {
    if (!confirm("작업을 중단하시겠습니까?")) return;
    try {
        await fetch('/api/cancel', { method: 'POST' });
        appendLog(`작업 중단 요청을 전송했습니다...`, 'warn');
    } catch (e) {
        console.error(e);
    }
});

// Init
checkExifTool();
