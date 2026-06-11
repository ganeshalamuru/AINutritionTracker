import TopBar from "./TopBar";
import BottomNav from "./BottomNav";

export default function Layout({ children }) {
  return (
    <div className="flex flex-col min-h-screen bg-gray-50">
      <TopBar />
      <main className="flex-1 max-w-md mx-auto w-full pb-20 px-4">
        {children}
      </main>
      <BottomNav />
    </div>
  );
}
