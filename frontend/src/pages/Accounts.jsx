import React, { useState, useEffect } from 'react'
import { getAccounts, importAccounts, deleteAccount, clearAccounts, batchDeleteAccounts, exportSessionKeys, exportRaw, authorizeOAuth, markUsed, markUnused, markDisabled, markEnabled, exportSub2api } from '../api'

const STATUS_COLORS = {
  idle: '#6b7280',
  running: '#2563eb',
  success: '#16a34a',
  failed: '#dc2626',
}

export default function Accounts() {
  const [accounts, setAccounts] = useState([])
  const [importText, setImportText] = useState('')
  const [msg, setMsg] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [exportText, setExportText] = useState('')
  const [authLoading, setAuthLoading] = useState({})
  const [detailLogs, setDetailLogs] = useState([])
  const [sub2apiLoading, setSub2apiLoading] = useState(false)
  const [filter, setFilter] = useState('all')

  const load = async () => {
    try {
      const res = await getAccounts()
      setAccounts(res.data.accounts || [])
    } catch {}
  }

  useEffect(() => { load() }, [])

  const handleImport = async () => {
    if (!importText.trim()) return
    try {
      const res = await importAccounts(importText)
      setMsg(`导入成功: +${res.data.added}, 跳过 ${res.data.skipped}, 总计 ${res.data.total}`)
      setImportText('')
      load()
    } catch (e) {
      setMsg('导入失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const handleDelete = async (id) => {
    await deleteAccount(id)
    selected.delete(id)
    setSelected(new Set(selected))
    load()
  }

  const handleClear = async () => {
    if (!confirm('确定清空所有账号？')) return
    await clearAccounts()
    setSelected(new Set())
    load()
  }

  const handleBatchDelete = async () => {
    if (selected.size === 0) return
    if (!confirm(`确定删除选中的 ${selected.size} 个账号？`)) return
    await batchDeleteAccounts(Array.from(selected))
    setSelected(new Set())
    setMsg(`已删除 ${selected.size} 个账号`)
    load()
  }

  const handleExportSK = async () => {
    const ids = selected.size > 0 ? Array.from(selected) : accounts.map(a => a.id)
    try {
      const res = await exportSessionKeys(ids)
      const keys = res.data.keys || []
      if (keys.length === 0) {
        setMsg('没有可导出的 sessionKey')
        return
      }
      navigator.clipboard.writeText(keys.join('\n'))
      setMsg(`已复制 ${keys.length} 个 sessionKey 到剪贴板`)
    } catch (e) {
      setMsg('导出失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const handleExportRaw = async () => {
    const ids = selected.size > 0 ? Array.from(selected) : accounts.map(a => a.id)
    try {
      const res = await exportRaw(ids)
      const lines = res.data.lines || []
      if (lines.length === 0) {
        setMsg('没有可导出的账号')
        return
      }
      navigator.clipboard.writeText(lines.join('\n'))
      setMsg(`已复制 ${lines.length} 个账号到剪贴板`)
    } catch (e) {
      setMsg('导出失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const handleCopyExport = () => {
    navigator.clipboard.writeText(exportText)
    setMsg('已复制到剪贴板')
  }

  const handleAuthorize = async (id) => {
    setAuthLoading(prev => ({ ...prev, [id]: true }))
    setDetailLogs([])
    try {
      const res = await authorizeOAuth(id)
      if (res.data.ok) {
        const url = res.data.redirect_url || ''
        setExportText(url)
        setMsg(`授权成功! 链接已生成`)
      } else {
        setMsg(`授权失败: ${res.data.error || '未知错误'} (step: ${res.data.step || ''})`)
        if (res.data.detail_logs) {
          setDetailLogs(res.data.detail_logs)
        }
      }
    } catch (e) {
      setMsg('授权失败: ' + (e.response?.data?.detail || e.message))
    }
    setAuthLoading(prev => ({ ...prev, [id]: false }))
  }

  const handleMarkUsed = async () => {
    const ids = selected.size > 0 ? Array.from(selected) : []
    if (ids.length === 0) return
    await markUsed(ids)
    setMsg(`已标记 ${ids.length} 个账号为已使用`)
    load()
  }

  const handleMarkUnused = async () => {
    const ids = selected.size > 0 ? Array.from(selected) : []
    if (ids.length === 0) return
    await markUnused(ids)
    setMsg(`已取消 ${ids.length} 个账号的已使用标记`)
    load()
  }

  const handleMarkDisabled = async (ids) => {
    if (!ids || ids.length === 0) return
    await markDisabled(ids)
    setMsg(`已标记 ${ids.length} 个账号为作废`)
    load()
  }

  const handleMarkEnabled = async (ids) => {
    if (!ids || ids.length === 0) return
    await markEnabled(ids)
    setMsg(`已取消 ${ids.length} 个账号的作废标记`)
    load()
  }

  const handleExportSub2api = async () => {
    const ids = selected.size > 0 ? Array.from(selected) : accounts.map(a => a.id)
    if (ids.length === 0) return
    setSub2apiLoading(true)
    setMsg(`正在生成 sub2api JSON (${ids.length} 个账号)...`)
    try {
      const res = await exportSub2api(ids)
      if (res.data.ok) {
        setExportText(JSON.stringify(res.data.data, null, 2))
        setMsg(`sub2api 导出完成: 成功 ${res.data.success}, 失败 ${res.data.failed}`)
      } else {
        setMsg(`导出失败: ${res.data.error}`)
      }
    } catch (e) {
      setMsg('导出失败: ' + (e.response?.data?.detail || e.message))
    }
    setSub2apiLoading(false)
  }

  const toggleSelect = (id) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  const selectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(filtered.map(a => a.id)))
    }
  }

  const filtered = accounts.filter(a => {
    if (filter === 'active') return !a.disabled
    if (filter === 'disabled') return a.disabled
    if (filter === 'used') return a.used
    if (filter === 'unused') return !a.used && !a.disabled
    return true
  })

  const disabledCount = accounts.filter(a => a.disabled).length

  const s = { input: { width: '100%', padding: 8, border: '1px solid #d1d5db', borderRadius: 6, fontSize: 13, fontFamily: 'monospace' } }
  const btnStyle = (bg) => ({ padding: '6px 14px', background: bg, color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 })

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>批量导入账号</h2>
      <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
        格式: 账号----密码----sk 或 账号----sk 或 仅 sk（一行一个）
      </p>
      <textarea
        value={importText}
        onChange={e => setImportText(e.target.value)}
        rows={5}
        placeholder={'user@example.com----password123----sk-ant-sid02-xxx\nuser2@example.com----sk-ant-sid02-yyy\nsk-ant-sid02-zzz'}
        style={s.input}
      />
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button onClick={handleImport} style={btnStyle('#2563eb')}>导入</button>
        <button onClick={handleClear} style={btnStyle('#dc2626')}>清空全部</button>
      </div>
      {msg && <p style={{ fontSize: 13, color: '#2563eb', marginTop: 8 }}>{msg}</p>}

      <div style={{ marginTop: 24, marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 16, margin: 0 }}>账号列表 ({filtered.length}/{accounts.length})</h2>
          <div style={{ display: 'flex', gap: 4 }}>
            {[
              { key: 'all', label: '全部' },
              { key: 'active', label: '正常' },
              { key: 'disabled', label: `作废(${disabledCount})` },
              { key: 'used', label: '已使用' },
              { key: 'unused', label: '未使用' },
            ].map(f => (
              <button key={f.key} onClick={() => { setFilter(f.key); setSelected(new Set()) }}
                style={{
                  padding: '2px 10px', fontSize: 12, borderRadius: 10, cursor: 'pointer',
                  border: filter === f.key ? '1px solid #2563eb' : '1px solid #d1d5db',
                  background: filter === f.key ? '#eff6ff' : '#fff',
                  color: filter === f.key ? '#2563eb' : '#6b7280',
                }}
              >{f.label}</button>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {selected.size > 0 && (
            <>
              <button onClick={handleMarkUsed} style={btnStyle('#f59e0b')}>标记已使用</button>
              <button onClick={handleMarkUnused} style={btnStyle('#6b7280')}>取消已使用</button>
              <button onClick={() => handleMarkDisabled(Array.from(selected))} style={btnStyle('#991b1b')}>标记作废</button>
              <button onClick={() => handleMarkEnabled(Array.from(selected))} style={btnStyle('#059669')}>取消作废</button>
              <button onClick={handleBatchDelete} style={btnStyle('#dc2626')}>删除({selected.size})</button>
              <span style={{ borderLeft: '1px solid #e5e7eb', margin: '0 2px' }} />
            </>
          )}
          <button onClick={handleExportRaw} style={btnStyle('#059669')}>原始导出</button>
          <button onClick={handleExportSK} style={btnStyle('#7c3aed')}>导出 SK</button>
          <button onClick={handleExportSub2api} disabled={sub2apiLoading} style={btnStyle(sub2apiLoading ? '#9ca3af' : '#0891b2')}>
            {sub2apiLoading ? '生成中...' : '导出 sub2api'}
          </button>
        </div>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: '#f9fafb', textAlign: 'left' }}>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb', width: 32 }}>
              <input type="checkbox" checked={filtered.length > 0 && selected.size === filtered.length} onChange={selectAll} />
            </th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>邮箱</th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>状态</th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>标记</th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>上次运行</th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(a => (
            <tr key={a.id} style={{ background: selected.has(a.id) ? '#eff6ff' : a.disabled ? '#f9fafb' : 'transparent', opacity: a.disabled ? 0.6 : 1 }}>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6' }}>
                <input type="checkbox" checked={selected.has(a.id)} onChange={() => toggleSelect(a.id)} />
              </td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6', textDecoration: a.disabled ? 'line-through' : 'none' }}>{a.email}</td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6' }}>
                <span style={{ color: STATUS_COLORS[a.status] || '#6b7280', fontWeight: 500 }}>
                  {a.status}
                </span>
                {a.last_error && <span style={{ color: '#dc2626', fontSize: 11, marginLeft: 4 }}>({a.last_error.slice(0, 40)})</span>}
              </td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6', whiteSpace: 'nowrap' }}>
                {a.disabled && (
                  <span style={{
                    display: 'inline-block', padding: '1px 8px', borderRadius: 10,
                    background: '#fee2e2', color: '#991b1b', fontSize: 12, fontWeight: 500, marginRight: 4,
                  }}>作废</span>
                )}
                {a.used && (
                  <span style={{
                    display: 'inline-block', padding: '1px 8px', borderRadius: 10,
                    background: '#fef3c7', color: '#92400e', fontSize: 12, fontWeight: 500,
                  }}>已使用</span>
                )}
                {!a.disabled && !a.used && <span style={{ color: '#9ca3af', fontSize: 12 }}>-</span>}
              </td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6', fontSize: 12, color: '#6b7280' }}>
                {a.last_run_at ? new Date(a.last_run_at).toLocaleString() : '-'}
              </td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6', whiteSpace: 'nowrap' }}>
                <button
                  onClick={() => handleAuthorize(a.id)}
                  disabled={authLoading[a.id]}
                  style={{
                    color: '#fff', background: authLoading[a.id] ? '#9ca3af' : '#7c3aed',
                    border: 'none', borderRadius: 4, cursor: authLoading[a.id] ? 'default' : 'pointer',
                    fontSize: 12, padding: '2px 8px', marginRight: 4,
                  }}
                >
                  {authLoading[a.id] ? '获取中...' : '获取授权'}
                </button>
                {a.disabled ? (
                  <button onClick={() => handleMarkEnabled([a.id])} style={{ color: '#059669', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, marginRight: 4 }}>
                    恢复
                  </button>
                ) : (
                  <button onClick={() => handleMarkDisabled([a.id])} style={{ color: '#991b1b', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, marginRight: 4 }}>
                    作废
                  </button>
                )}
                <button onClick={() => handleDelete(a.id)} style={{ color: '#dc2626', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }}>
                  删除
                </button>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr><td colSpan={6} style={{ padding: 20, textAlign: 'center', color: '#9ca3af' }}>暂无账号</td></tr>
          )}
        </tbody>
      </table>

      {detailLogs.length > 0 && (
        <div style={{ marginTop: 16, padding: 12, background: '#fef2f2', borderRadius: 6, border: '1px solid #fecaca' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ fontSize: 14, color: '#991b1b', margin: 0 }}>授权详细日志</h3>
            <button onClick={() => setDetailLogs([])} style={{ color: '#991b1b', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }}>关闭</button>
          </div>
          <pre style={{ fontSize: 11, color: '#374151', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 300, overflow: 'auto' }}>
            {detailLogs.join('\n')}
          </pre>
        </div>
      )}

      {exportText && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ fontSize: 14, color: '#6b7280', margin: 0 }}>导出的 SessionKey</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={handleCopyExport} style={btnStyle('#16a34a')}>复制</button>
              <button onClick={() => setExportText('')} style={{ ...btnStyle('#9ca3af') }}>关闭</button>
            </div>
          </div>
          <textarea
            readOnly
            value={exportText}
            rows={Math.min(8, exportText.split('\n').length + 1)}
            style={{ ...s.input, background: '#f9fafb' }}
          />
        </div>
      )}
    </div>
  )
}
