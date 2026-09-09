// Where a node stands, as a badge a reader can interrogate: the label, and
// the reason beside it or on hover — because a status nobody can question is
// one they either trust blindly or ignore.
export function Standing({
  label,
  reason,
  sound,
  brief = false,
}: {
  label: string;
  reason: string;
  sound: boolean;
  brief?: boolean;
}) {
  return (
    <span className={sound ? "standing sound" : "standing unsound"} title={reason}>
      {label}
      {!brief && reason !== "" && <span className="reason"> — {reason}</span>}
    </span>
  );
}
