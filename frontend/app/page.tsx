import { redirect } from "next/navigation";

// トップに来たら最新版(/v1)へ飛ばす。旧版は /v0 に残してある。
export default function Home() {
  redirect("/v1");
}
