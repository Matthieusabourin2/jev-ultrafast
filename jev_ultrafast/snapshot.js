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
  const hoverOnly = e => hoverRow(e) && !e.checkVisibility({checkOpacity:true}) &&
    getComputedStyle(e).pointerEvents==='none';
  const reachable = e => { if (visible(e)) return true;
    if (!hoverRow(e)) return false;
    if (e.closest('[aria-hidden="true"],[inert]') || !e.checkVisibility({checkVisibilityCSS:true})) return false;
    if (hoverOnly(e)) return true;
    const r=e.getBoundingClientRect(), hit=document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
    return !!hit && (hit===e || e.contains(hit)); };
  const name = (e,seen=new Set()) => {
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
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const POPUP='dialog[open],[role="dialog"],[role="alertdialog"],[aria-modal="true"],[role="listbox"],[role="menu"]';
  // While a modal is open the rest of the page is inert to the user: offer only the modal's controls
  // (and popups it opened, such as a list rendered at the end of <body>).
  const modal=[...document.querySelectorAll('dialog,[aria-modal="true"]')].reverse()
    .find(d=>(d.matches('dialog:modal') || d.getAttribute('aria-modal')==='true') && d.checkVisibility());
  const inModal=e=>!modal || modal.contains(e) || !!e.closest('[role="listbox"],[role="menu"],[role="tooltip"]');
  const actions=[];
  for (const e of document.querySelectorAll(selector)) {
    if (!inModal(e) || !safe(e) || !reachable(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0) continue;
    // Inside an open dialog, menu or list, a control past the visible edge is still offered (after every
    // on-screen control, the nearest 40 only): the executor scrolls it into view before acting. Elsewhere only
    // controls on screen count, and only if nothing covers them.
    const onScreen=x>=0 && y>=0 && x<innerWidth && y<innerHeight;
    if (!onScreen && !e.closest(POPUP)) continue;
    // Row controls that ignore the pointer until their row is hovered are reachable: the executor hovers first.
    if (onScreen && !e.closest(POPUP) && !hoverOnly(e)) {
      const hit=document.elementFromPoint(x,y);
      if (hit && hit!==e && !e.contains(hit) && !hit.contains(e) && !hit.closest('label')?.contains(e)) continue;
    }
    if (/1password|bitwarden|lastpass|dashlane|keeper/i.test(name(e)+' '+e.tagName+' '+(e.id||''))) continue;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    // named: the control has an accessible name (not a test-id hint or its role); menu: it opens a popup.
    const own=name(e);
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
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  // Plain elements made clickable by script (cards, rows) carry no role: take the outermost element showing a
  // pointer cursor that holds text and no control of its own.
  const seen=new Set(actions.map(a=>cache.nodes.get(a.node)));
  for (const e of document.body.querySelectorAll('div,li,span,td,article,section,img')) {
    if (getComputedStyle(e).cursor!=='pointer' || (e.parentElement && getComputedStyle(e.parentElement).cursor==='pointer')) continue;
    if (seen.has(e) || !inModal(e) || e.closest(selector) || e.querySelector(selector) || !visible(e)) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
    if (r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight || r.height>400) continue;
    const label=(e.getAttribute('aria-label')||e.innerText||e.getAttribute('alt')||'').trim().replace(/\s+/g,' ').slice(0,120);
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
    const context=row?.innerText?.trim().replace(/\s+/g,' ').replace(a.label,'').trim().slice(0,60);
    if (context) { a.base=a.label; a.label+=' · '+context; }
  }
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  // On-screen controls first; then the nearest off-screen ones from an open popup, at most 40.
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
    if (!inModal(e) || e.scrollHeight<=e.clientHeight+2 || !/(auto|scroll)/.test(getComputedStyle(e).overflowY) || !visible(e)) continue;
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
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions};
})()
