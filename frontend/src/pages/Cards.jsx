import React, { useState, useEffect } from 'react'
import { getCards, importCards, deleteCard, clearCards, markCardsUsed, markCardsUnused } from '../api'

export default function Cards() {
  const [cards, setCards] = useState([])
  const [importText, setImportText] = useState('')
  const [msg, setMsg] = useState('')
  const [selected, setSelected] = useState(new Set())

  const load = async () => {
    try {
      const res = await getCards()
      setCards(res.data.cards || [])
    } catch {}
  }

  useEffect(() => { load() }, [])

  const handleImport = async () => {
    if (!importText.trim()) return
    try {
      const res = await importCards(importText)
      setMsg(`导入成功: +${res.data.added}, 跳过 ${res.data.skipped}, 总计 ${res.data.total}`)
      setImportText('')
      load()
    } catch (e) {
      setMsg('导入失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const handleDelete = async (index) => {
    await deleteCard(index)
    selected.delete(index)
    setSelected(new Set(selected))
    load()
  }

  const handleClear = async () => {
    if (!confirm('确定清空所有卡片？')) return
    await clearCards()
    setSelected(new Set())
    load()
  }

  const handleMarkUsed = async () => {
    if (selected.size === 0) return
    await markCardsUsed(Array.from(selected))
    setMsg(`已标记 ${selected.size} 张卡为已用`)
    setSelected(new Set())
    load()
  }

  const handleMarkUnused = async () => {
    if (selected.size === 0) return
    await markCardsUnused(Array.from(selected))
    setMsg(`已取消 ${selected.size} 张卡的已用标记`)
    setSelected(new Set())
    load()
  }

  const toggleSelect = (index) => {
    const next = new Set(selected)
    next.has(index) ? next.delete(index) : next.add(index)
    setSelected(next)
  }

  const selectAll = () => {
    if (selected.size === cards.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(cards.map(c => c.id)))
    }
  }

  const s = { input: { width: '100%', padding: 8, border: '1px solid #d1d5db', borderRadius: 6, fontSize: 13, fontFamily: 'monospace' } }
  const btnStyle = (bg) => ({ padding: '6px 14px', background: bg, color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 })

  const available = cards.filter(c => !c.used && !c.claimed).length

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>导入卡片</h2>
      <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
        格式: 卡号:xxx;CVV:xxx;有效期:MM/YYYY 或 卡号|有效期|CVV（一行一张）
      </p>
      <textarea
        value={importText}
        onChange={e => setImportText(e.target.value)}
        rows={4}
        placeholder={'卡号:5259620104181393;CVV:228;有效期:11/2028\n4111111111111111|12/2027|123'}
        style={s.input}
      />
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button onClick={handleImport} style={btnStyle('#2563eb')}>导入</button>
        <button onClick={handleClear} style={btnStyle('#dc2626')}>清空全部</button>
      </div>
      {msg && <p style={{ fontSize: 13, color: '#2563eb', marginTop: 8 }}>{msg}</p>}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 24, marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, margin: 0 }}>
          卡片列表 ({cards.length})
          <span style={{ fontSize: 13, color: '#6b7280', fontWeight: 400, marginLeft: 8 }}>
            可用 {available}
          </span>
        </h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {selected.size > 0 && (
            <>
              <button onClick={handleMarkUsed} style={btnStyle('#f59e0b')}>
                标记已用 ({selected.size})
              </button>
              <button onClick={handleMarkUnused} style={btnStyle('#6b7280')}>
                取消标记 ({selected.size})
              </button>
            </>
          )}
        </div>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: '#f9fafb', textAlign: 'left' }}>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb', width: 32 }}>
              <input type="checkbox" checked={cards.length > 0 && selected.size === cards.length} onChange={selectAll} />
            </th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>卡号</th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>有效期</th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>状态</th>
            <th style={{ padding: 8, borderBottom: '1px solid #e5e7eb' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {cards.map(c => (
            <tr key={c.id} style={{ background: selected.has(c.id) ? '#eff6ff' : 'transparent' }}>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6' }}>
                <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggleSelect(c.id)} />
              </td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6', fontFamily: 'monospace' }}>{c.number_masked}</td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6' }}>{c.expiry || '-'}</td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6' }}>
                {c.used ? (
                  <span style={{ display: 'inline-block', padding: '1px 8px', borderRadius: 10, background: '#fee2e2', color: '#991b1b', fontSize: 12, fontWeight: 500 }}>已用</span>
                ) : c.claimed ? (
                  <span style={{ display: 'inline-block', padding: '1px 8px', borderRadius: 10, background: '#fef3c7', color: '#92400e', fontSize: 12, fontWeight: 500 }}>使用中</span>
                ) : (
                  <span style={{ display: 'inline-block', padding: '1px 8px', borderRadius: 10, background: '#dcfce7', color: '#166534', fontSize: 12, fontWeight: 500 }}>可用</span>
                )}
              </td>
              <td style={{ padding: 8, borderBottom: '1px solid #f3f4f6' }}>
                <button onClick={() => handleDelete(c.id)} style={{ color: '#dc2626', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }}>
                  删除
                </button>
              </td>
            </tr>
          ))}
          {cards.length === 0 && (
            <tr><td colSpan={5} style={{ padding: 20, textAlign: 'center', color: '#9ca3af' }}>暂无卡片</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
