import AlertDetailClient from "./AlertDetailClient";

export function generateStaticParams() {
  return [{ id: "placeholder" }];
}

export default function AlertDetailPage() {
  return <AlertDetailClient />;
}
