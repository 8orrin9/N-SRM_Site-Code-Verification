// 가중치 설정 항목 옆에 붙는 (i) 호버 설명 아이콘.
export default function InfoTip({ text }: { text: string }) {
  return (
    <span className="info-tip" tabIndex={0}>
      <span className="info-tip-icon">i</span>
      <span className="info-tip-bubble">{text}</span>
    </span>
  );
}
