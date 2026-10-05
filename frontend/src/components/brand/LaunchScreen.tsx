/*
 * Cold-start screen of the installed app, pure CSS (globals.css, .launch-*), so
 * it paints with the server HTML and leaves on its own whatever the scripts do.
 * The faint trace is what the iOS launch image shows (public/splash, from
 * scripts/generate_splash.py), so the hand-off from the OS splash has no jump;
 * the pen then inks the hemicycle and the Speaker's seat hops onto its place,
 * as in LogoReveal. Timing is shared with Stenografo, Fascicoli and Scranno.
 *
 * Render it inside ThemeProvider: next-themes' script must set data-theme
 * before this layer is parsed, or a dark device paints one light frame.
 *
 * The script runs before the layer is parsed. In standalone mode it marks the
 * session's later loads (data-launched hides the layer) and, on iOS, centres
 * the mark on the whole screen as in the launch image: with the default status
 * bar iOS lays the page out below it. ?launch=1 forces the layer in any tab and
 * ?launch=still freezes its first frame, for screenshots and the splash script.
 */
const ARC = "M 35.91 139.73 A 81 81 0 1 1 188.09 139.73";
const DOT = { cx: 112, cy: 146, r: 22 };

const flags = `(function(){var d=document.documentElement;try{var q=/[?&]launch=(1|still)(&|$)/.exec(location.search);if(q)d.dataset.launch=q[1];var n=navigator.standalone===true;if(n)d.dataset.standalone="";if(n||matchMedia("(display-mode: standalone)").matches){if(sessionStorage.getItem("launched"))d.dataset.launched="";else sessionStorage.setItem("launched","1")}var s=screen.height-innerHeight;if(n&&innerWidth===screen.width&&s>0&&s<100)d.style.setProperty("--launch-dy",s/2+"px")}catch(e){}})();`;

export function LaunchScreen() {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: flags }} />
      <div className="launch" aria-hidden="true">
        <svg viewBox="0 8 224 166" width={112} height={83} className="launch-mark" focusable="false">
          <g className="launch-ghost">
            <path d={ARC} fill="none" strokeWidth={32} strokeLinecap="round" />
            <circle cx={DOT.cx} cy={DOT.cy} r={DOT.r} />
          </g>
          <path className="launch-stroke" d={ARC} pathLength={1} fill="none" strokeWidth={32} strokeLinecap="round" />
          <circle className="launch-dot" cx={DOT.cx} cy={DOT.cy} r={DOT.r} />
        </svg>
      </div>
    </>
  );
}
