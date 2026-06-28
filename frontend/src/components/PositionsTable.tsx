export function PositionsTable({ cash }: { cash: string }) {
  return (
    <div>
      <h3>Cash</h3>
      <p>{Number(cash).toFixed(2)} USD</p>
    </div>
  );
}
