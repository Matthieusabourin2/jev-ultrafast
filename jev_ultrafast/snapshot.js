(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  // Row controls often stay at opacity 0 until hovered (the executor hovers before clicking): keep a control
  // that is rendered and receives the pointer at its centre, even while transparent.
  // A hover row: a list/table row, or an ancestor carrying a Tailwind-style hover group class ("group", "group/x").
  const hoverRow = e => !!e.closest('li,tr,[role="row"],[role="listitem"],[role="gridcell"],[role="treeitem"],article') ||
    (() => { for (let a=e.parentElement, i=0; a && i<6; a=a.parentElement, i++)
      if ([...a.classList].some(c=>c==='group' || c.startsWith('group/'))) return true; return false; })();
  // Transparent and pointer-inert until its row is hovered: the executor hovers first, then clicks.
  const hoverOnly = e => !e.checkVisibility({checkOpacity:true}) && getComputedStyle(e).pointerEvents==='none' &&
    hoverRow(e);
  // A counter drawn over a transparent range input (travellers, rooms): the input is what holds the value, and
  // the executor sets it by value, so it counts as reachable although the pointer lands on the drawing.
  const counter = e => e.tagName==='INPUT' && e.type==='range' && !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkVisibilityCSS:true});
  const reachable = e => { if (visible(e) || counter(e)) return true;
    if (!hoverRow(e)) return false;
    if (e.closest('[aria-hidden="true"],[inert]') || !e.checkVisibility({checkVisibilityCSS:true})) return false;
    if (hoverOnly(e)) return true;
    const r=e.getBoundingClientRect(), hit=document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
    return !!hit && (hit===e || e.contains(hit)); };
  // Icon fonts draw glyphs from the Unicode private-use area: meaningless to the model, drop them.
  const clean = s => (s||'').replace(/[\ue000-\uf8ff]/g,'').replace(/\s+/g,' ').trim();
  const name = (e,seen=new Set()) => clean(rawName(e,seen));
  const rawName = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  // Icon-only controls (common in web apps) have no accessible name: fall back to the hints a developer left.
  const hint = e => {
    const described=(e.getAttribute('aria-describedby')||'').split(/\s+/)
      .map(id=>document.getElementById(id)?.textContent.trim()).filter(Boolean).join(' ');
    const svgTitle=e.querySelector('svg title')?.textContent.trim();
    const test=e.getAttribute('data-testid')||e.getAttribute('data-test')||e.getAttribute('data-qa')||
      e.getAttribute('data-test-id')||'';
    return described || svgTitle || test.replace(/[-_]+/g,' ').replace(/([a-z])([A-Z])/g,'$1 $2').trim();
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const CONTROL_TAGS=new Set(['BUTTON','INPUT','TEXTAREA','SELECT','SUMMARY']);
  const isControl = e => CONTROL_TAGS.has(e.tagName) || (e.tagName==='A' && e.hasAttribute('href')) ||
    roles.includes(e.getAttribute('role')) || e.getAttribute('contenteditable')==='true';
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (e.type==='range') return 'slider';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  // Where a hand would click: the first spot of the element that the element itself receives. A link wrapped over
  // two lines has its box centre on the paragraph; a result row is often a click layer under its own texts (Google
  // Flights), covered at the centre but free along its edges. Try fragment centres, then a grid over the box.
  cache.point=(e,grid=true)=>{
    const takes=(x,y)=>x>=0 && y>=0 && x<innerWidth && y<innerHeight && e.contains(document.elementFromPoint(x,y));
    for (const q of e.getClientRects()) {
      const x=q.x+q.width/2, y=q.y+q.height/2;
      if (q.width && q.height && takes(x,y)) return {x,y,takes:true};
    }
    const r=e.getBoundingClientRect();
    if (grid && r.width>=8 && r.height>=8)
      for (const fy of [0.5,0.2,0.8]) for (const fx of [0.5,0.1,0.3,0.7,0.9,0.03,0.97]) {
        const x=r.x+r.width*fx, y=r.y+r.height*fy;
        if (takes(x,y)) return {x,y,takes:true};
      }
    return {x:r.x+r.width/2, y:r.y+r.height/2};
  };
  const DIALOG='dialog,[role="dialog"],[role="alertdialog"]';
  cache.dialogText=d=>(d?.innerText||'').slice(0,4000);
  // Same document, route and hash; a query rewritten while filling (Google Flights' tfs) is not a new page.
  // Committing clicks compare the whole page instead (Browser.strict).
  cache.pageKey=()=>[performance.timeOrigin,location.origin+location.pathname+location.hash,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    // Rendered, even if transparent until hovered: such a control keeps a guard (its row's text).
    if (!e?.isConnected || e.closest('[aria-hidden="true"],[inert]') || !e.checkVisibility({checkVisibilityCSS:true})) return null;
    // A row's text guards against a recycled row (virtualized lists reuse nodes for another item); a dialog or a
    // form changing around the control (prices loading in a calendar) does not change what the control means.
    const scope=e.closest('article,li,tr,[role="row"]');
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const POPUP='dialog[open],[role="dialog"],[role="alertdialog"],[aria-modal="true"],[role="listbox"],[role="menu"]';
  // While a modal is open the rest of the page is inert to the user: offer only the modal's controls
  // (and popups it opened, such as a list rendered at the end of <body>).
  const modal=[...document.querySelectorAll('dialog,[aria-modal="true"]')].reverse()
    .find(d=>(d.matches('dialog:modal') || d.getAttribute('aria-modal')==='true') && d.checkVisibility() &&
      // A dialog still animating is opening or closing (Google Flights' calendar after "Done"): not modal yet.
      !d.getAnimations().some(a=>a.playState==='running') &&
      getComputedStyle(d).opacity!=='0');
  const inModal=e=>!modal || modal.contains(e) || !!e.closest('[role="listbox"],[role="menu"],[role="tooltip"]');
  const actions=[];
  // Open popups and small grids (calendars), listed once: an off-screen control inside one is still offered.
  const popups=[...document.querySelectorAll(POPUP)].filter(d=>d.checkVisibility());
  const calendars=[...document.querySelectorAll('[role="grid"]')]
    .filter(g=>g.checkVisibility() && g.querySelectorAll('[role="gridcell"]').length<=100);
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e) || e.matches(':disabled')) continue;
    // Position first, as the original does: most controls of a long page are off screen and leave here cheaply.
    const r=e.getBoundingClientRect();
    if (r.width<=0 || r.height<=0) continue;
    const away=r.bottom<0 || r.top>=innerHeight || r.right<0 || r.left>=innerWidth;
    const smallGrid=()=>calendars.some(g=>g.contains(e)), inPopup=()=>popups.some(d=>d.contains(e));
    if (away && !inPopup() && !smallGrid()) continue;
    if (e.closest('[aria-disabled="true"]') || !inModal(e) || !reachable(e)) continue;
    // Reachable is all the read needs: fragments and centre. The executor searches the box for a free spot.
    const {x,y,takes}=cache.point(e,false), rname=role(e);
    if (!rname) continue;
    // Inside an open dialog, menu or list, a control past the visible edge is still offered (after every
    // on-screen control, the nearest 40 only): the executor scrolls it into view before acting. Elsewhere only
    // controls on screen count, and only if nothing covers them.
    const onScreen=x>=0 && y>=0 && x<innerWidth && y<innerHeight;
    // A calendar (a small grid) runs past the fold too; a mail list or a data table (a large grid) does not count.
    if (!onScreen && !inPopup() && !smallGrid()) continue;
    // Row controls that ignore the pointer until their row is hovered are reachable: the executor hovers first.
    if (onScreen && !takes && !e.closest(POPUP) && !hoverOnly(e) &&
        !(counter(e) && e.parentElement?.parentElement?.contains(document.elementFromPoint(x,y)))) {
      const hit=document.elementFromPoint(x,y);
      // Covered by its own card's plain content (a result row's texts over its click layer) still counts, as a
      // label over its input does; covered by anything else (a dialog, a backdrop, another control) does not.
      const ownContent=hit && e.parentElement?.contains(hit) && !hit.closest(selector);
      if (hit && hit!==e && !e.contains(hit) && !hit.contains(e) && !hit.closest('label')?.contains(e) && !ownContent) continue;
    }
    const own=name(e);  // named: the control has an accessible name (not a test-id hint or its role)
    if (/1password|bitwarden|lastpass|dashlane|keeper/i.test(own+' '+e.tagName+' '+(e.id||''))) continue;
    // A calendar day is often a cell wrapping its own button or checkbox: offer the control, not both.
    if (rname==='gridcell' && e.querySelector('button,a[href],[role="button"],[role="checkbox"],[role="link"],[role="option"]')) continue;
    // menu: it opens a popup.
    const base={node:identity(e),role:rname,label:own||hint(e)||rname,named:!!own,offscreen:!onScreen,
      menu:e.hasAttribute('aria-haspopup') || e.hasAttribute('aria-expanded'),
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (e.tagName==='SELECT' && e.options.length>30) {
      // One option per action would flood the action space (and push later controls past the cap):
      // a long list is filled like a text field, and the executor picks the option whose label matches.
      actions.push({...base,kind:'fill',value:[...e.selectedOptions].map(o=>o.label).join(', ')});
    } else if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) || counter(e) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      // A suggestion's first line is what it names ("Montpellier" above "France"): the executor compares it with
      // what was typed.
      if (rname==='option') base.first=clean((e.innerText||'').split('\n').find(l=>l.trim())||'');
      actions.push({...base,kind:editable?'fill':'click',value});
      // "Open X" exists for input fields, as in the original (a date field opens its calendar: Google Flights'
      // Departure); a text area or a rich editor is just filled, and offering a click there let the model click it
      // forever (claude.ai project instructions).
      const opens=e.tagName==='INPUT' && !counter(e);
      if (editable && opens) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  // Plain elements made clickable by script (cards, rows) carry no role: take the outermost element showing a
  // pointer cursor that holds text and no control of its own.
  // Descend from <body>, skipping controls, hidden and off-screen subtrees, and stop at the first pointer element
  // of each branch (the outermost one): a full scan styled every element (25 ms on a 12,000-node page).
  const seen=new Set(actions.map(a=>cache.nodes.get(a.node))), cards=[];
  const descend=parent=>{
    for (const e of parent.children) {
      if (isControl(e)) continue;
      const r=e.getBoundingClientRect();
      if (r.height>0 && (r.bottom<0 || r.top>innerHeight)) continue;
      const style=getComputedStyle(e);
      if (style.display==='none' || style.visibility==='hidden' && !e.children.length) continue;
      if (style.cursor==='pointer') cards.push(e); else descend(e);
    }
  };
  descend(document.body);
  for (const e of cards) {
    if (!/^(DIV|LI|SPAN|TD|ARTICLE|SECTION|IMG)$/.test(e.tagName)) continue;
    if (seen.has(e) || !inModal(e) || e.querySelector(selector) || !visible(e)) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
    if (r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight || r.height>400) continue;
    const label=clean(e.getAttribute('aria-label')||e.innerText||e.getAttribute('alt')||'').slice(0,120);
    if (!label) continue;
    actions.push({node:identity(e),role:'button',label,named:true,rect:{x:r.x,y:r.y,w:r.width,h:r.height},kind:'click',value:''});
  }
  // The same label on several rows ("…", "Edit") is ambiguous to the model: name the row it belongs to.
  const counts={};
  for (const a of actions) counts[a.label]=(counts[a.label]||0)+1;
  for (const a of actions) {
    if (counts[a.label]<2 || a.kind==='select') continue;
    // The nearest row-like ancestor, else the nearest ancestor (up to 5 levels) holding text besides the label.
    let row=cache.nodes.get(a.node)?.closest('li,tr,[role="row"],[role="listitem"],article,[role="article"]');
    for (let up=cache.nodes.get(a.node)?.parentElement, i=0; !row && up && i<5; up=up.parentElement, i++) {
      const extra=(up.innerText||'').replace(a.label,'').trim();
      if (extra && extra.length<300) row=up;
    }
    const context=clean(row?.innerText).replace(a.label,'').trim().slice(0,60);
    if (context) { a.base=a.label; a.label+=' · '+context; }
  }
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=clean(node.textContent), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    if (/^(1password|bitwarden|lastpass|dashlane)\b.{0,60}(available|disponible)/i.test(value)) continue;  // extension overlay
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  const page_key=cache.pageKey(), guards={}, dialogs={}, boxes=new Map();
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // The text of the dialog holding a control ("Delete project A?"): a committing click requires it unchanged.
  for (const a of actions) {
    const d=cache.nodes.get(a.node)?.closest(DIALOG);
    if (d) { if (!boxes.has(d)) boxes.set(d,cache.dialogText(d)); dialogs[a.node]=boxes.get(d); }
  }
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  // On-screen controls first; then the nearest off-screen ones from an open popup or a grid, at most 40.
  const near=a=>Math.max(0,-a.rect.y,a.rect.y-innerHeight);
  const offscreen=actions.filter(a=>a.offscreen).sort((a,b)=>near(a)-near(b));
  actions.splice(0,actions.length,...actions.filter(a=>!a.offscreen),...offscreen.slice(0,40));
  actions.forEach(a=>delete a.offscreen);
  const omitted_actions=Math.max(0,actions.length-250)+Math.max(0,offscreen.length-40);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  // Web apps often keep the document still and scroll a panel (<main>, a list): scroll the largest such panel
  // when it covers at least half the viewport, else the document.
  let pane=null, area=0, popup=false;
  for (const e of document.body.querySelectorAll('main,section,div,ul,form,dialog,[role]')) {
    if (e.scrollHeight<=e.clientHeight+2 || e.clientHeight<60 || !/(auto|scroll)/.test(getComputedStyle(e).overflowY) ||
        !inModal(e) || !visible(e)) continue;
    const r=e.getBoundingClientRect(), a=Math.max(0,Math.min(r.right,innerWidth)-Math.max(r.left,0))*
      Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,0)), inPopup=!!e.closest(POPUP);
    if (a>0 && (inPopup && !popup || inPopup===popup && a>area)) { pane=e; area=a; popup=inPopup; }
  }
  if (pane && (popup || area>=innerWidth*innerHeight/2)) {
    const r=pane.getBoundingClientRect(), x=Math.max(r.left,0)+Math.min(r.width,innerWidth)/2,
      y=Math.max(r.top,0)+Math.min(r.height,innerHeight)/2;
    if (pane.scrollTop+pane.clientHeight<pane.scrollHeight-2)
      actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down to reveal elements and text below the visible area',delta:Math.round(pane.clientHeight*0.8),x,y});
    if (pane.scrollTop>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-Math.round(pane.clientHeight*0.8),x,y});
  } else {
    if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down to reveal elements and text below the visible area',delta:560});
    if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  }
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,dialogs,omitted_actions};
})()
