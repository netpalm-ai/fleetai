export function BrandMark({ large = false }: { large?: boolean }) {
  return (
    <span className={large ? "brand brand-large" : "brand"}>
      Fleet<span>AI</span>
    </span>
  );
}
