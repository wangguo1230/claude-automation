import React, { useState, useEffect } from 'react'
import { getConfig, updateConfig, generateIban, testVless, getVlessStatus } from '../api'

export default function Config() {
  const [cfg, setCfg] = useState({})
  const [msg, setMsg] = useState('')
  const [vlessTestResult, setVlessTestResult] = useState(null)
  const [vlessTesting, setVlessTesting] = useState(false)
  const [vlessStatus, setVlessStatus] = useState(null)

  useEffect(() => {
    getConfig().then(r => setCfg(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    if (!cfg.vless_enabled) return
    getVlessStatus().then(r => setVlessStatus(r.data)).catch(() => {})
    const timer = setInterval(() => {
      getVlessStatus().then(r => setVlessStatus(r.data)).catch(() => {})
    }, 5000)
    return () => clearInterval(timer)
  }, [cfg.vless_enabled])

  const handleSave = async () => {
    try {
      const res = await updateConfig(cfg)
      setCfg(res.data)
      setMsg('配置已保存')
      setTimeout(() => setMsg(''), 2000)
    } catch (e) {
      setMsg('保存失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const handleGenIban = async () => {
    try {
      const res = await generateIban(cfg.iban_country || 'DE')
      setCfg({ ...cfg, iban: res.data.iban })
    } catch {}
  }

  const handleTestVless = async () => {
    setVlessTesting(true)
    setVlessTestResult(null)
    try {
      const res = await testVless(cfg.vless_share_link || '', cfg.vless_xray_path || '')
      setVlessTestResult(res.data)
    } catch (e) {
      setVlessTestResult({ ok: false, message: e.response?.data?.detail || e.message })
    }
    setVlessTesting(false)
  }

  const field = (label, key, opts = {}) => {
    const { type = 'text', options, placeholder } = opts
    return (
      <label style={{ display: 'block', marginBottom: 12 }}>
        <span style={{ display: 'block', fontSize: 13, fontWeight: 500, color: '#374151', marginBottom: 4 }}>{label}</span>
        {options ? (
          <select
            value={cfg[key] || ''}
            onChange={e => setCfg({ ...cfg, [key]: e.target.value })}
            style={{ width: '100%', padding: 8, border: '1px solid #d1d5db', borderRadius: 6, fontSize: 13 }}
          >
            {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        ) : type === 'toggle' ? (
          <div>
            <button
              onClick={() => setCfg({ ...cfg, [key]: !cfg[key] })}
              style={{
                padding: '4px 12px',
                background: cfg[key] ? '#16a34a' : '#9ca3af',
                color: '#fff', border: 'none', borderRadius: 12, cursor: 'pointer', fontSize: 12,
              }}
            >
              {cfg[key] ? 'ON' : 'OFF'}
            </button>
          </div>
        ) : type === 'number' ? (
          <input
            type="number"
            value={cfg[key] ?? ''}
            onChange={e => setCfg({ ...cfg, [key]: parseInt(e.target.value) || 1 })}
            style={{ width: '100%', padding: 8, border: '1px solid #d1d5db', borderRadius: 6, fontSize: 13 }}
          />
        ) : (
          <input
            value={cfg[key] || ''}
            onChange={e => setCfg({ ...cfg, [key]: e.target.value })}
            placeholder={placeholder || ''}
            style={{ width: '100%', padding: 8, border: '1px solid #d1d5db', borderRadius: 6, fontSize: 13 }}
          />
        )}
      </label>
    )
  }

  return (
    <div style={{ maxWidth: 500 }}>
      <h2 style={{ fontSize: 16, marginBottom: 16 }}>全局配置</h2>

      <h3 style={{ fontSize: 14, color: '#6b7280', marginBottom: 8 }}>浏览器设置</h3>
      {field('浏览器模式', 'browser_provider', { options: [{ value: 'adspower', label: 'AdsPower 指纹浏览器' }, { value: 'local_chrome', label: '本地 Chrome' }] })}

      {cfg.browser_provider === 'local_chrome' ? (
        <>
          {field('Chrome 路径（留空自动检测）', 'chrome_path')}
          {field('无头模式', 'chrome_headless', { type: 'toggle' })}
        </>
      ) : (
        <>
          {field('AdsPower API 地址', 'adspower_api_base')}
          {field('AdsPower 分组 ID', 'adspower_group_id')}
        </>
      )}

      <hr style={{ margin: '16px 0', border: 'none', borderTop: '1px solid #e5e7eb' }} />
      <h3 style={{ fontSize: 14, color: '#6b7280', marginBottom: 8 }}>
        VLESS 代理
        {cfg.vless_enabled && vlessStatus && (
          <span style={{
            marginLeft: 8, display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
            background: vlessStatus.running ? '#16a34a' : '#dc2626',
            verticalAlign: 'middle',
          }} title={vlessStatus.message || ''} />
        )}
      </h3>
      <p style={{ fontSize: 12, color: '#9ca3af', marginBottom: 8 }}>
        内置 xray VLESS 代理，将 vless:// 分享链接转为本地 HTTP 代理供浏览器使用
      </p>
      {field('启用 VLESS', 'vless_enabled', { type: 'toggle' })}
      {cfg.vless_enabled && (
        <>
          {field('VLESS 分享链接', 'vless_share_link', { placeholder: 'vless://uuid@host:port?security=reality&sni=...&pbk=...&type=tcp#name' })}
          {field('xray 可执行文件路径', 'vless_xray_path', { placeholder: 'C:/path/to/xray.exe' })}
          <div style={{ marginTop: -4, marginBottom: 12 }}>
            <button
              onClick={handleTestVless}
              disabled={vlessTesting || !cfg.vless_share_link || !cfg.vless_xray_path}
              style={{
                padding: '5px 14px',
                background: vlessTesting ? '#9ca3af' : '#7c3aed',
                color: '#fff', border: 'none', borderRadius: 6, cursor: vlessTesting ? 'default' : 'pointer', fontSize: 12,
              }}
            >
              {vlessTesting ? '测试中...' : '测试连通性'}
            </button>
            {vlessTestResult && (
              <div style={{
                marginTop: 8, padding: 10, borderRadius: 6, fontSize: 12,
                background: vlessTestResult.ok ? '#f0fdf4' : '#fef2f2',
                border: `1px solid ${vlessTestResult.ok ? '#bbf7d0' : '#fecaca'}`,
                color: vlessTestResult.ok ? '#166534' : '#991b1b',
              }}>
                <div style={{ fontWeight: 500 }}>{vlessTestResult.message}</div>
                {vlessTestResult.ok && vlessTestResult.local_url && (
                  <div style={{ marginTop: 4, color: '#6b7280' }}>
                    本地代理: {vlessTestResult.local_url}
                    {vlessTestResult.exit_ip && ` | 出口: ${vlessTestResult.exit_ip} ${vlessTestResult.exit_country || ''}`}
                    {vlessTestResult.exit_org && ` (${vlessTestResult.exit_org})`}
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}

      <hr style={{ margin: '16px 0', border: 'none', borderTop: '1px solid #e5e7eb' }} />
      <h3 style={{ fontSize: 14, color: '#6b7280', marginBottom: 8 }}>SEPA 扩展</h3>
      <p style={{ fontSize: 12, color: '#9ca3af', marginBottom: 8 }}>
        加载 Claude SEPA Helper 扩展到浏览器，自动配置账单信息并触发 SEPA 面板
      </p>
      {field('扩展目录路径（含 manifest.json）', 'sepa_extension_path', { placeholder: 'C:/path/to/claude-sepa-helper/' })}

      <hr style={{ margin: '16px 0', border: 'none', borderTop: '1px solid #e5e7eb' }} />
      <h3 style={{ fontSize: 14, color: '#6b7280', marginBottom: 8 }}>订阅设置</h3>
      {field(cfg.vless_enabled ? '代理（VLESS 启用时作为回退）' : '代理', 'proxy')}
      {field('订阅计划', 'plan', { options: [{ value: 'max', label: 'Max ($200/月)' }, { value: 'pro', label: 'Pro ($20/月)' }] })}
      {field('计费周期', 'billing_period', { options: [{ value: 'annual', label: '年付 (Save 50%)' }, { value: 'monthly', label: '月付' }] })}
      {field('支付方式', 'payment_method', { options: [{ value: 'sepa', label: 'SEPA (IBAN)' }, { value: 'card', label: '信用卡' }] })}
      {cfg.payment_method !== 'card' && (
        <>
          {field('IBAN', 'iban')}
          <div style={{ marginTop: -8, marginBottom: 12 }}>
            <button
              onClick={handleGenIban}
              style={{ padding: '4px 10px', background: '#6b7280', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
            >
              随机生成 IBAN
            </button>
          </div>
          {field('IBAN 国家', 'iban_country', { options: [{ value: 'DE', label: 'DE - 德国' }, { value: 'FR', label: 'FR - 法国' }, { value: 'NL', label: 'NL - 荷兰' }, { value: 'AT', label: 'AT - 奥地利' }] })}
        </>
      )}
      {cfg.payment_method === 'card' && (
        <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
          信用卡模式：请在「卡片管理」页导入卡号，打开浏览器后将自动选择套餐、填写卡号和随机免税州地址并提交订阅
        </p>
      )}
      {field('最大并发数', 'max_concurrent', { type: 'number' })}
      {field('自动点击 Subscribe', 'auto_subscribe', { type: 'toggle' })}

      <button onClick={handleSave} style={{ padding: '8px 24px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 500, marginTop: 8 }}>
        保存配置
      </button>
      {msg && <span style={{ marginLeft: 12, color: '#16a34a', fontSize: 13 }}>{msg}</span>}
    </div>
  )
}
