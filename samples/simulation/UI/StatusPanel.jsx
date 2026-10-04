/*---
schema_version: 1
id: J001
kind: jsx
default_props: basic
---*/
function StatusPanel(props) {
  const data = (props && typeof props.data === "object" && props.data) || {};
  const day = Number.isFinite(data.day) ? data.day : 1;
  const time = data.time || "아침";
  const gold = Number.isFinite(data.gold) ? data.gold : 0;
  const reputation = Math.max(0, Math.min(10, Number(data.reputation) || 0));
  const location = data.location || "-";

  return (
    <div style={{border: "1px solid #8a7a5c", borderRadius: 8, padding: "8px 12px", fontSize: 14, background: "#f6f0e4", color: "#3a3226"}}>
      <div style={{fontWeight: 600}}>{day}일째 · {time} · {location}</div>
      <div style={{display: "flex", gap: 16, marginTop: 4}}>
        <span>골드 {gold}</span>
        <span>평판 {"★".repeat(reputation)}{"☆".repeat(10 - reputation)}</span>
      </div>
    </div>
  );
}
