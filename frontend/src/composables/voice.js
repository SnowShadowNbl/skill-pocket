// 语音转文字：麦克风 → AudioWorklet 重采样成 16kHz 16bit PCM → WebSocket → 后端 → FunASR（2pass 流式）
// 注意：浏览器只在 HTTPS（或 localhost）下允许使用麦克风。

const WORKLET = `
class Pcm16Writer extends AudioWorkletProcessor {
  constructor() {
    super()
    this.ratio = sampleRate / 16000
    this.t = 0
    this.last = 0
    this.out = []
  }
  process(inputs) {
    const input = inputs[0] && inputs[0][0]
    if (!input) return true
    let sq = 0
    for (let i = 0; i < input.length; i++) sq += input[i] * input[i]
    // 线性插值重采样到 16kHz，小数位置跨块保留
    while (this.t < input.length) {
      const i = Math.floor(this.t)
      const f = this.t - i
      const a = i < 0 ? this.last : input[i]
      const b = i + 1 < input.length ? input[i + 1] : input[i]
      this.out.push(a + (b - a) * f)
      this.t += this.ratio
    }
    this.t -= input.length
    this.last = input[input.length - 1]
    if (this.out.length >= 1600) {
      const pcm = new Int16Array(this.out.length)
      for (let k = 0; k < this.out.length; k++) {
        const s = Math.max(-1, Math.min(1, this.out[k]))
        pcm[k] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      this.out = []
      this.port.postMessage({ pcm: pcm.buffer, level: Math.sqrt(sq / input.length) }, [pcm.buffer])
    }
    return true
  }
}
registerProcessor('pcm16-writer', Pcm16Writer)
`

export function voiceSupported() {
  return !!(window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.AudioWorkletNode)
}

/**
 * 开始一次语音识别。onText(全文) 实时回调；返回 { stop(): Promise<string>, cancel() }。
 * 2pass 协议：online 是边说边出的增量文字；offline 是整句修正后的结果，会替换掉对应的 online 部分。
 */
export async function startVoice({ onText, onLevel, onError }) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  const ctx = new AudioContext()
  const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
  await ctx.audioWorklet.addModule(url)
  URL.revokeObjectURL(url)
  const source = ctx.createMediaStreamSource(stream)
  const node = new AudioWorkletNode(ctx, 'pcm16-writer')
  const mute = ctx.createGain()
  mute.gain.value = 0
  source.connect(node)
  node.connect(mute).connect(ctx.destination) // 接到输出才会持续处理；增益 0 不会回放出声

  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/asr/ws`)
  ws.binaryType = 'arraybuffer'
  const pending = []
  let offline = ''
  let online = ''
  let finished = null
  let closed = false

  ws.onopen = () => {
    ws.send(JSON.stringify({ mode: '2pass', chunk_size: [5, 10, 5], chunk_interval: 10, wav_name: 'h5', is_speaking: true, itn: true, hotwords: '' }))
    pending.splice(0).forEach((b) => ws.send(b))
  }
  ws.onmessage = (e) => {
    let msg
    try {
      msg = JSON.parse(e.data)
    } catch {
      return
    }
    if (msg.error) {
      onError?.(msg.error)
      return
    }
    if (msg.mode === '2pass-offline' || msg.mode === 'offline') {
      offline += msg.text || ''
      online = ''
    } else {
      online += msg.text || ''
    }
    onText?.(offline + online)
    if (msg.is_final && finished) finished()
  }
  ws.onerror = () => onError?.('语音服务连接失败')
  ws.onclose = () => {
    closed = true
    finished?.()
  }

  node.port.onmessage = ({ data }) => {
    onLevel?.(data.level)
    if (ws.readyState === WebSocket.OPEN) ws.send(data.pcm)
    else if (ws.readyState === WebSocket.CONNECTING) pending.push(data.pcm)
  }

  function release() {
    stream.getTracks().forEach((t) => t.stop())
    node.port.onmessage = null
    ctx.close().catch(() => {})
  }

  return {
    async stop() {
      release()
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ is_speaking: false }))
        // 等离线模型给出最终结果，最多 5 秒
        await new Promise((resolve) => {
          finished = resolve
          if (closed) resolve()
          setTimeout(resolve, 5000)
        })
      }
      try {
        ws.close()
      } catch {}
      return (offline + online).trim()
    },
    cancel() {
      release()
      try {
        ws.close()
      } catch {}
    },
  }
}
