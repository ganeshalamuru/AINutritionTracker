export default function Spinner({ text = "Loading..." }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-gray-500">
      <div className="w-8 h-8 border-3 border-green-500 border-t-transparent rounded-full animate-spin" style={{ borderWidth: 3 }} />
      <p className="text-sm">{text}</p>
    </div>
  );
}
