import { useState } from 'react'
import { downloadFile, resumesApi } from './api.js'

// B12 PDF로 내보내기(10/30): 문항별 최신 버전으로 기본 템플릿 PDF. 본문 개인정보는 가린 채로(서버).
// 제출용 연락처는 여기서 입력한 값만 PDF 상단에 넣고 저장하지 않는다
export default function PdfExport({ resumeId, onClose }) {
  const [contact, setContact] = useState({ name: '', phone: '', email: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const set = (k) => (e) => setContact({ ...contact, [k]: e.target.value })

  const run = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const out = await resumesApi.exportPdf(resumeId, { contact })
      await downloadFile(out.download_path, out.filename)
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card pdf-export" onSubmit={run}>
      <div className="row">
        <h2 className="grow">PDF로 내보내기</h2>
        <button type="button" className="secondary" onClick={onClose}>닫기</button>
      </div>
      <p className="muted">
        문항별 최신 버전으로 만듭니다. 본문 속 개인정보는 가려서 나오고, 아래에 입력한 연락처만 맨 위에 들어갑니다(저장하지 않음).
      </p>
      <div className="pdf-contact">
        <input placeholder="이름(선택)" value={contact.name} onChange={set('name')} maxLength={50} aria-label="이름" />
        <input placeholder="전화번호(선택)" value={contact.phone} onChange={set('phone')} maxLength={30} aria-label="전화번호" />
        <input type="email" placeholder="이메일(선택)" value={contact.email} onChange={set('email')} maxLength={254}
          aria-label="이메일" />
        <button type="submit" disabled={busy}>{busy ? '만드는 중…' : 'PDF 만들기'}</button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}
