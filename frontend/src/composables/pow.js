import { api } from '../api'

// 取一道人机校验题，在 Worker 里算出答案。返回 { pow_token, pow_nonce }
export async function solveChallenge() {
  const ch = await api('/api/auth/challenge')
  const worker = new Worker(new URL('../workers/pow.worker.js', import.meta.url), { type: 'module' })
  try {
    const nonce = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('安全校验超时，请重试')), 30000)
      worker.onmessage = ({ data }) => {
        clearTimeout(timer)
        resolve(data.nonce)
      }
      worker.onerror = () => {
        clearTimeout(timer)
        reject(new Error('安全校验失败，请刷新页面后重试'))
      }
      worker.postMessage({ salt: ch.salt, bits: ch.bits })
    })
    return { pow_token: ch.token, pow_nonce: nonce }
  } finally {
    worker.terminate()
  }
}
