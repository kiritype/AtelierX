import icon from '../assets/icon.svg';

// The app icon and name, at the left of each screen's header.
export function AppMark({ size = 20, name = true }: { size?: number; name?: boolean }) {
  return (
    <span className="app-mark">
      <img src={icon} width={size} height={size} alt={name ? '' : 'AtelierX'} />
      {name && <span>AtelierX</span>}
    </span>
  );
}
