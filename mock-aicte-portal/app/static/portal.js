document.addEventListener('DOMContentLoaded',()=>{
  // Match VerifyFlow's short, purposeful motion while respecting system motion preferences.
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer=window.matchMedia('(hover: hover) and (pointer: fine)');
  const revealItems=[...document.querySelectorAll('.page-heading,.feature,.catalogue-card,.metric,.hero-panel,.card.padded,.auth-form')];
  if(!reduced.matches&&'IntersectionObserver' in window){
    document.body.classList.add('motion-ready');
    const observer=new IntersectionObserver(entries=>{entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('is-visible');observer.unobserve(entry.target)}})},{threshold:.06,rootMargin:'0px 0px -32px 0px'});
    revealItems.forEach((element,index)=>{element.classList.add('reveal');element.style.transitionDelay=`${Math.min(index*30,150)}ms`;observer.observe(element)});
  }
  if(!reduced.matches&&finePointer.matches){
    let pointerFrame=0;
    window.addEventListener('pointermove',event=>{cancelAnimationFrame(pointerFrame);pointerFrame=requestAnimationFrame(()=>{document.documentElement.style.setProperty('--cursor-x',`${event.clientX}px`);document.documentElement.style.setProperty('--cursor-y',`${event.clientY}px`)})},{passive:true});
    document.querySelectorAll('.hero-panel,.feature,.catalogue-card,.metric,.auth-form').forEach(element=>{
      element.classList.add('tilt-surface');let frame=0;
      element.addEventListener('pointermove',event=>{if(event.pointerType!=='mouse'||element.matches(':focus-within'))return;const rect=element.getBoundingClientRect();const x=(event.clientX-rect.left)/rect.width;const y=(event.clientY-rect.top)/rect.height;const amplitude=Math.min(7,Math.max(1.5,1200/Math.max(rect.width,rect.height)));cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{element.style.setProperty('--glare-x',`${(x*100).toFixed(1)}%`);element.style.setProperty('--glare-y',`${(y*100).toFixed(1)}%`);element.style.transform=`perspective(1100px) rotateX(${((.5-y)*amplitude).toFixed(2)}deg) rotateY(${((x-.5)*amplitude).toFixed(2)}deg) translateY(-3px)`;element.classList.add('is-tilting')})});
      const reset=()=>{cancelAnimationFrame(frame);element.style.transform='';element.classList.remove('is-tilting')};element.addEventListener('pointerleave',reset);element.addEventListener('focusin',reset);
    });
  }
  const menu=document.querySelector('[data-open-nav]');const backdrop=document.querySelector('[data-close-nav]');const sidebar=document.getElementById('workspace-nav');
  if(menu&&sidebar){const close=()=>{document.body.classList.remove('nav-open');menu.setAttribute('aria-expanded','false');menu.focus()};menu.addEventListener('click',()=>{const open=document.body.classList.toggle('nav-open');menu.setAttribute('aria-expanded',String(open));if(open)sidebar.querySelector('a')?.focus()});backdrop?.addEventListener('click',close);sidebar.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>{document.body.classList.remove('nav-open');menu.setAttribute('aria-expanded','false')}));document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('nav-open'))close()})}
  const feedback=document.getElementById('registration-feedback');
  const quickFill=document.getElementById('evaluator-quick-fill');
  if(quickFill){
    fetch('/api/evaluator-credentials',{cache:'no-store',credentials:'same-origin'}).then(response=>response.ok?response.json():null).then(data=>{
      const accounts=data?.accounts;if(!Array.isArray(accounts)||!accounts.length)return;
      const links=quickFill.querySelector('.quick-fill-links');const form=quickFill.closest('form');
      accounts.forEach(account=>{
        const button=document.createElement('button');button.type='button';button.className='quick-fill-link';button.textContent=account.label;
        button.setAttribute('aria-label',`Auto-fill ${account.label} credentials`);
        button.addEventListener('click',()=>{
          form.elements.username.value=account.username;form.elements.password.value=account.password;
          form.elements.username.dispatchEvent(new Event('input',{bubbles:true}));
          form.elements.password.dispatchEvent(new Event('input',{bubbles:true}));
          form.elements.username.focus();
        });
        links.appendChild(button);
      });
      quickFill.hidden=false;
    }).catch(()=>{});
  }
  if(feedback){const {errors={},values={}}=JSON.parse(feedback.textContent);Object.entries(values).forEach(([name,value])=>{const input=document.querySelector(`[name="${name}"]`);if(input&&input.type!=='password')input.value=value});Object.entries(errors).forEach(([name,message])=>{const input=document.querySelector(`[name="${name}"]`);if(input){input.setAttribute('aria-invalid','true');const detail=document.createElement('small');detail.className='field-error';detail.textContent=message;input.insertAdjacentElement('afterend',detail)}})}
  document.querySelectorAll('[data-confirm]').forEach(form=>form.addEventListener('submit',e=>{if(!window.confirm(form.dataset.confirm))e.preventDefault()}));
  document.addEventListener('submit',async event=>{
    const form=event.target;
    if(!(form instanceof HTMLFormElement)||!form.matches('.upload-form'))return;
    event.preventDefault();
    if(form.dataset.submitting==='true')return;
    form.dataset.submitting='true';
    const button=event.submitter;
    if(button)button.disabled=true;
    const feedback=(message,kind)=>{
      const evidence=document.getElementById('evidence');
      evidence?.querySelector('[data-upload-feedback]')?.remove();
      const notice=document.createElement('div');
      notice.dataset.uploadFeedback='';notice.className=`alert ${kind}`;notice.setAttribute('role','status');notice.textContent=message;
      evidence?.querySelector('.card-title')?.insertAdjacentElement('afterend',notice);
    };
    try{
      const apiUrl=form.action.replace('/applications/','/api/applications/').replace(/\/upload$/,'/documents');
      const response=await fetch(apiUrl,{method:'POST',body:new FormData(form),credentials:'same-origin'});
      const outcome=await response.json();
      if(!response.ok||!outcome.ok)throw new Error(outcome.error||'Upload failed. Please try again.');
      const page=await fetch(window.location.pathname,{credentials:'same-origin'});
      if(!page.ok)throw new Error('Document uploaded. Refresh the application to see the updated checklist.');
      const fresh=new DOMParser().parseFromString(await page.text(),'text/html');
      for(const id of ['evidence','submission']){
        const current=document.getElementById(id),replacement=fresh.getElementById(id);
        if(current&&replacement)current.replaceWith(replacement);
      }
      feedback('Document uploaded. Checklist updated.','success');
    }catch(error){feedback(error.message||'Upload failed. Please try again.','error')}
    finally{form.dataset.submitting='false';if(button)button.disabled=false}
  },true);
  document.querySelectorAll('form[data-loading]').forEach(form=>form.addEventListener('submit',event=>{
    if(event.defaultPrevented)return;
    if(form.dataset.submitting==='true'){event.preventDefault();return}
    form.dataset.submitting='true';
    const button=event.submitter;
    if(button){button.setAttribute('aria-disabled','true');button.textContent='Working…'}
  }));
  const search=document.querySelector('[data-table-search]'),filter=document.querySelector('[data-table-filter]');
  if(search||filter){const update=()=>{const table=document.getElementById((search||filter).dataset.tableSearch||(search||filter).dataset.tableFilter);table?.querySelectorAll('tbody tr:not(.empty-row)').forEach(row=>{const text=row.textContent.toLowerCase();row.hidden=Boolean((search?.value&&!text.includes(search.value.toLowerCase()))||(filter?.value&&row.dataset.status!==filter.value))})};search?.addEventListener('input',update);filter?.addEventListener('change',update)}
});
