import React, { useState, useEffect, useRef } from 'react'
import { startTasks, startAutoTasks, stopTasks, getTaskStatus, getTaskLogs, confirmTask, openBrowser, fillCard } from '../api'

const STATUS_COLORS = {
  idle: '#6b7280',
  running: '#2563eb',
  success: '#16a34a',
  failed: '#dc2626',
  waiting: '#f59e0b',
}

const STATUS_LABELS = {
  idle: '等待',
  running: '运行中',
  success: '成功',
  failed: '失败',
  waiting: '等待确认',
}

export default function Tasks() {
  const [accounts, setAccounts] = useState([])
  const [running, setRunning] = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [expandedLogs, setExpandedLogs] = useState({})
  const [logs, setLogs] = useState({})
  const [msg, setMsg] = useState('')
  const timerRef = useRef(null)

  const loadStatus = async () => {
    try {
      const res = await getTaskStatus()
      setAccounts(res.data.accounts || [])
      setRunning(res.data.running)
    } catch {}
  }

  useEffect(() => {
    loadStatus()
    timerRef.current = setInterval(loadStatus, 2000)
    return () => clearInterval(timerRef.current)
  }, [])

  const handleStart = async () => {
    const ids = selected.size > 0 ? Array.from(selected) : null
    await startTasks(ids)
    loadStatus()
  }

  const handleStartAuto = async () => {
    const ids = selected.size > 0 ? Array.from(selected) : null
    await startAutoTasks(ids)
    loadStatus()
  }

  const handleStop = async () => {
    await stopTasks()
    loadStatus()
  }

  const toggleSelect = (id) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  const selectAll = () => {
    if (selected.size === accounts.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(accounts.map(a => a.id)))
    }
  }

  const toggleLogs = async (id) => {
    const next = { ...expandedLogs }
    if (next[id]) {
      delete next[id]
    } else {
      next[id] = true
      try {
        const res = await getTaskLogs(id)
        setLogs(prev => ({ ...prev, [id]: res.data.logs || [] }))
      } catch {}
    }
    setExpandedLogs(next)
  }

  const refreshLogs = async (id) => {
    try {
      const res = await getTaskLogs(id)
      setLogs(prev => ({ ...prev, [id]: res.data.logs || [] }))
    } catch {}
  }

  const handleFillCard = async (id) => {
    setMsg('正在填卡...')
    try {
      const res = await fillCard(id)
      if (res.data.ok) {
        setMsg('填卡订阅完成')
      } else {
        setMsg('填卡失败: ' + (res.data.error || '未知错误'))
      }
      loadStatus()
    } catch (e) {
      setMsg('填卡失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const handleConfirm = async (id) => {
    try {
      const res = await confirmTask(id)
      if (res.data.ok) {
        setMsg('已确认完成' + (res.data.new_session_key ? '，sessionKey 已更新' : ''))
      } else {
        setMsg('确认失败: ' + (res.data.error || '未知错误'))
      }
      loadStatus()
    } catch (e) {
      setMsg('确认失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const successCount = accounts.filter(a => a.status === 'success').length
  const failedCount = accounts.filter(a => a.status === 'failed').length
  const runningCount = accounts.filter(a => a.status === 'running').length
  const waitingCount = accounts.filter(a => a.status === 'waiting').length

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
        <button
          onClick={handleStartAuto}
          disabled={running}
          style={{
            padding: '8px 20px', background: running ? '#9ca3af' : '#ea580c',
            color: '#fff', border: 'none', borderRadius: 6, cursor: running ? 'default' : 'pointer', fontWeight: 600,
          }}
        >
          {selected.size > 0 ? `运行 (${selected.size})` : '全部运行'}
        </button>
        <button
          onClick={handleStart}
          disabled={running}
          style={{
            padding: '8px 20px', background: running ? '#9ca3af' : '#16a34a',
            color: '#fff', border: 'none', borderRadius: 6, cursor: running ? 'default' : 'pointer', fontWeight: 500,
          }}
        >
          {selected.size > 0 ? `打开浏览器 (${selected.size})` : '全部打开浏览器'}
        </button>
        <button
          onClick={handleStop}
          disabled={!running}
          style={{
            padding: '8px 20px', background: running ? '#dc2626' : '#9ca3af',
            color: '#fff', border: 'none', borderRadius: 6, cursor: running ? 'pointer' : 'default', fontWeight: 500,
          }}
        >
          关闭所有浏览器
        </button>

        <div style={{ marginLeft: 'auto', fontSize: 13, color: '#6b7280' }}>
          总计 {accounts.length}
          {runningCount > 0 && <span style={{ color: '#2563eb', marginLeft: 8 }}>运行 {runningCount}</span>}
          {successCount > 0 && <span style={{ color: '#16a34a', marginLeft: 8 }}>成功 {successCount}</span>}
          {waitingCount > 0 && <span style={{ color: '#f59e0b', marginLeft: 8 }}>待确认 {waitingCount}</span>}
          {failedCount > 0 && <span style={{ color: '#dc2626', marginLeft: 8 }}>失败 {failedCount}</span>}
        </div>
      </div>

      {msg && <p style={{ fontSize: 13, color: '#2563eb', marginBottom: 8 }}>{msg}</p>}

      {accounts.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
          暂无账号，请先到「账号管理」导入
        </div>
      ) : (
        <div>
          <div style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 12, color: '#6b7280', cursor: 'pointer' }}>
              <input type="checkbox" checked={selected.size === accounts.length} onChange={selectAll} style={{ marginRight: 4 }} />
              全选
            </label>
          </div>

          {accounts.map(a => (
            <div key={a.id} style={{ border: '1px solid #e5e7eb', borderRadius: 8, marginBottom: 8, overflow: 'hidden' }}>
              <div
                style={{ display: 'flex', alignItems: 'center', padding: '10px 12px', cursor: 'pointer', background: '#fafafa' }}
                onClick={() => toggleLogs(a.id)}
              >
                <input
                  type="checkbox"
                  checked={selected.has(a.id)}
                  onChange={(e) => { e.stopPropagation(); toggleSelect(a.id) }}
                  style={{ marginRight: 10 }}
                />
                <span
                  style={{ flex: 1, fontSize: 13, cursor: 'pointer', userSelect: 'none' }}
                  onClick={(e) => { e.stopPropagation(); toggleSelect(a.id) }}
                >{a.email}</span>
                <span style={{
                  fontSize: 12, fontWeight: 600, padding: '2px 10px', borderRadius: 10,
                  background: (STATUS_COLORS[a.status] || '#6b7280') + '18', color: STATUS_COLORS[a.status] || '#6b7280',
                }}>
                  {a.status === 'running' && '⏳ '}{a.status === 'waiting' && '🔔 '}{STATUS_LABELS[a.status] || a.status}
                </span>
                {a.has_browser && (
                  <button
                    onClick={(e) => { e.stopPropagation(); openBrowser(a.id) }}
                    style={{
                      marginLeft: 8, padding: '3px 12px', background: '#8b5cf6', color: '#fff',
                      border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 500,
                    }}
                  >
                    聚焦浏览器
                  </button>
                )}
                {a.has_browser && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleFillCard(a.id) }}
                    style={{
                      marginLeft: 4, padding: '3px 12px', background: '#ea580c', color: '#fff',
                      border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 500,
                    }}
                  >
                    填卡订阅
                  </button>
                )}
                {a.has_browser && (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleConfirm(a.id) }}
                    style={{
                      marginLeft: 4, padding: '3px 12px', background: '#16a34a', color: '#fff',
                      border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 600,
                    }}
                  >
                    确认完成
                  </button>
                )}
                {!a.has_browser && a.status !== 'running' && (
                  <>
                    <button
                      onClick={(e) => { e.stopPropagation(); startAutoTasks([a.id]).then(loadStatus) }}
                      style={{
                        marginLeft: 8, padding: '3px 12px', background: '#ea580c', color: '#fff',
                        border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 600,
                      }}
                    >
                      运行
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); startTasks([a.id]).then(loadStatus) }}
                      style={{
                        marginLeft: 4, padding: '3px 12px', background: '#2563eb', color: '#fff',
                        border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 500,
                      }}
                    >
                      打开浏览器
                    </button>
                  </>
                )}
                {a.last_log && (
                  <span style={{ fontSize: 11, color: '#9ca3af', marginLeft: 8, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {a.last_log}
                  </span>
                )}
              </div>

              {expandedLogs[a.id] && (
                <div style={{ padding: '8px 12px', background: '#111827', maxHeight: 200, overflowY: 'auto' }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 4 }}>
                    <button onClick={() => refreshLogs(a.id)} style={{ fontSize: 11, color: '#60a5fa', background: 'none', border: 'none', cursor: 'pointer' }}>
                      刷新日志
                    </button>
                  </div>
                  {(logs[a.id] || []).length === 0 ? (
                    <div style={{ color: '#6b7280', fontSize: 12 }}>暂无日志</div>
                  ) : (
                    (logs[a.id] || []).map((line, i) => (
                      <div key={i} style={{ fontSize: 11, fontFamily: 'monospace', color: line.includes('ERROR') ? '#f87171' : line.includes('成功') || line.includes('完成') ? '#4ade80' : '#d1d5db', lineHeight: 1.6 }}>
                        {line}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
