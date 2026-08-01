import React, { useState } from 'react'
import Accounts from './pages/Accounts'
import Cards from './pages/Cards'
import Config from './pages/Config'
import Tasks from './pages/Tasks'

const tabs = [
  { key: 'tasks', label: '浏览器管理' },
  { key: 'accounts', label: '账号管理' },
  { key: 'cards', label: '卡片管理' },
  { key: 'config', label: '全局配置' },
]

export default function App() {
  const [active, setActive] = useState('tasks')

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 20, fontFamily: '-apple-system, sans-serif' }}>
      <h1 style={{ fontSize: 22, marginBottom: 16 }}>Claude 账号管理</h1>

      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '2px solid #e5e7eb' }}>
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            style={{
              padding: '8px 20px',
              border: 'none',
              background: active === t.key ? '#2563eb' : 'transparent',
              color: active === t.key ? '#fff' : '#374151',
              borderRadius: '6px 6px 0 0',
              cursor: 'pointer',
              fontWeight: active === t.key ? 600 : 400,
              fontSize: 14,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {active === 'tasks' && <Tasks />}
      {active === 'accounts' && <Accounts />}
      {active === 'cards' && <Cards />}
      {active === 'config' && <Config />}
    </div>
  )
}
