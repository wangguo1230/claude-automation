import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const getAccounts = () => api.get('/accounts')
export const importAccounts = (text) => api.post('/accounts/import', { text })
export const deleteAccount = (id) => api.delete(`/accounts/${id}`)
export const clearAccounts = () => api.delete('/accounts')
export const batchDeleteAccounts = (ids) => api.post('/accounts/batch-delete', { ids })
export const exportSessionKeys = (ids) => api.post('/accounts/export-sk', { ids })
export const exportRaw = (ids) => api.post('/accounts/export-raw', { ids })
export const markUsed = (ids) => api.post('/accounts/mark-used', { ids })
export const markUnused = (ids) => api.post('/accounts/mark-unused', { ids })
export const markDisabled = (ids) => api.post('/accounts/mark-disabled', { ids })
export const markEnabled = (ids) => api.post('/accounts/mark-enabled', { ids })
export const exportSub2api = (ids) => api.post('/accounts/export-sub2api', { ids })

export const getCards = () => api.get('/cards')
export const importCards = (text) => api.post('/cards/import', { text })
export const deleteCard = (index) => api.delete(`/cards/${index}`)
export const clearCards = () => api.delete('/cards')
export const markCardsUsed = (ids) => api.post('/cards/mark-used', { ids })
export const markCardsUnused = (ids) => api.post('/cards/mark-unused', { ids })

export const getConfig = () => api.get('/config')
export const updateConfig = (data) => api.put('/config', data)
export const generateIban = (country) => api.get(`/config/generate-iban?country=${country || 'DE'}`)

export const startTasks = (accountIds) => api.post('/tasks/start', { account_ids: accountIds || null })
export const startAutoTasks = (accountIds) => api.post('/tasks/start-auto', { account_ids: accountIds || null })
export const stopTasks = () => api.post('/tasks/stop')
export const getTaskStatus = () => api.get('/tasks/status')
export const getTaskLogs = (accountId, sinceId = 0) => api.get(`/tasks/${accountId}/logs?since_id=${sinceId}`)
export const confirmTask = (accountId) => api.post(`/tasks/${accountId}/confirm`)
export const openBrowser = (accountId) => api.post(`/tasks/${accountId}/open-browser`)
export const fillCard = (accountId) => api.post(`/tasks/${accountId}/fill-card`)

export const authorizeOAuth = (accountId, proxy) => api.post('/oauth/authorize', { account_id: accountId, proxy })

export const testVless = (shareLink, xrayPath) => api.post('/config/vless/test', { share_link: shareLink, xray_path: xrayPath })
export const getVlessStatus = () => api.get('/config/vless/status')
