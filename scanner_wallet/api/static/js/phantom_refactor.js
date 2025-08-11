// phantom_refactor.js
// Refactor Phantom integration : évite multi-modals, nettoie listeners et simplifie UX

let phantomWallet = null;
let isPhantomConnected = false;
let connectionInProgress = false;
const PHANTOM = { timeout: 10_000 };

function log(...args){ console.log('[PHANTOM]', ...args); }

async function detectPhantomWallet(){
  if (typeof window.solana === 'undefined') return false;
  return !!window.solana.isPhantom;
}

async function connectPhantomWallet(){
  if (connectionInProgress) return false;
  connectionInProgress = true;

  try {
    const ok = await detectPhantomWallet();
    if (!ok){
      showPhantomInstallModal();
      return false;
    }

    // request connection with timeout guard
    const connectPromise = window.solana.connect({ onlyIfTrusted: false });
    const res = await promiseTimeout(connectPromise, PHANTOM.timeout);
    if (res?.publicKey){
      phantomWallet = res.publicKey.toString();
      isPhantomConnected = true;
      setupPhantomListeners();
      updateWalletUI(true);
      showNotification('Phantom connecté', 'success');
      return true;
    }
    throw new Error('No publicKey');
  } catch (err){
    if (err.name === 'TimeoutError') showNotification('Phantom: délai de connexion dépassé', 'error');
    else if (err.code === 4001) showNotification('Connexion refusée', 'warning');
    else console.error(err);
    return false;
  } finally {
    connectionInProgress = false;
  }
}

function promiseTimeout(promise, ms){
  let id; const timeout = new Promise((_, rej)=> id = setTimeout(()=> rej(new Error('TimeoutError')), ms));
  return Promise.race([promise, timeout]).finally(()=> clearTimeout(id));
}

function setupPhantomListeners(){
  if (!window.solana) return;
  // ensure we don't attach multiple listeners
  window.solana.removeEventListener?.('disconnect', handlePhantomDisconnect);
  window.solana.on?.('disconnect', handlePhantomDisconnect);
}

function handlePhantomDisconnect(){
  phantomWallet = null;
  isPhantomConnected = false;
  updateWalletUI(false);
  showNotification('Phantom déconnecté', 'info');
}

// Update UI - reuse existing DOM nodes, minimal writes
function updateWalletUI(connected){
  const connectBtn = document.querySelector('.wallet-connect-btn');
  const walletInfo = document.getElementById('wallet-info');
  const walletAddressSpan = document.getElementById('wallet-address');

  if (connected && phantomWallet){
    if (connectBtn) connectBtn.style.display = 'none';
    if (walletInfo) { walletInfo.style.display = 'flex'; walletAddressSpan.textContent = `${phantomWallet.slice(0,4)}...${phantomWallet.slice(-4)}`; }
    updatePhantomSidebarStatus(true, phantomWallet);
  } else {
    if (connectBtn) connectBtn.style.display = 'flex';
    if (walletInfo) walletInfo.style.display = 'none';
    updatePhantomSidebarStatus(false);
  }
}

function updatePhantomSidebarStatus(connected, address=null){
  const phantomStatus = document.getElementById('phantom-status');
  const phantomIcon = document.getElementById('phantom-icon');
  const phantomText = document.getElementById('phantom-text');
  if (!phantomStatus) return;
  if (connected && address){
    phantomStatus.classList.add('connected');
    if (phantomIcon) phantomIcon.textContent = '👻✅';
    if (phantomText) phantomText.textContent = `Phantom: ${address.slice(0,6)}...`;
  } else {
    phantomStatus.classList.remove('connected');
    if (phantomIcon) phantomIcon.textContent = '👻';
    if (phantomText) phantomText.textContent = 'Phantom: Déconnecté';
  }
}

// Modal management: reuse single container
let _singleModal = null;
function ensureModal(){
  if (!_singleModal){
    _singleModal = document.createElement('div');
    _singleModal.className = 'global-single-modal';
    Object.assign(_singleModal.style, { position:'fixed', top:0,left:0,right:0,bottom:0, display:'flex',alignItems:'center',justifyContent:'center', zIndex:10000 });
    document.body.appendChild(_singleModal);
    _singleModal.addEventListener('click', (e)=> { if (e.target === _singleModal) closeModal(); });
  }
  return _singleModal;
}

function showPhantomInstallModal(){
  const modal = ensureModal();
  modal.innerHTML = `
    <div style="background:var(--glass-bg); padding:24px; border-radius:12px; max-width:420px;">
      <h3>Phantom requis</h3>
      <p>Installez Phantom pour trader via votre navigateur.</p>
      <div style="display:flex; gap:8px; margin-top:12px;">
        <button id="phantom-install-btn">Installer Phantom</button>
        <button id="phantom-close-btn">Fermer</button>
      </div>
    </div>`;
  document.getElementById('phantom-install-btn').onclick = ()=> window.open('https://phantom.app/', '_blank');
  document.getElementById('phantom-close-btn').onclick = closeModal;
  modal.style.background = 'rgba(0,0,0,0.6)';
}

function closeModal(){ if (_singleModal) _singleModal.innerHTML = ''; }

// Trading helpers (open Jupiter)
function buyToken(tokenMint){ ensureConnected().then(ok => { if (!ok) return; const url = `https://jup.ag/swap/So11111111111111111111111111111111111111112-${tokenMint}?amount=1`; window.open(url,'_blank'); showNotification('Achat ouvert', 'success'); }); }
function sellToken(tokenMint){ ensureConnected().then(ok => { if (!ok) return; const url = `https://jup.ag/swap/${tokenMint}-So11111111111111111111111111111111111111112`; window.open(url,'_blank'); showNotification('Vente ouverte', 'success'); }); }

async function ensureConnected(){
  if (isPhantomConnected && phantomWallet) return true;
  return await connectPhantomWallet();
}

// simplified notification (reuses single element)
let _notifEl = null;
function showNotification(msg, type='info', duration=2500){
  if (!_notifEl){
    _notifEl = document.createElement('div');
    _notifEl.style.position='fixed';
    _notifEl.style.top='80px';
    _notifEl.style.right='20px';
    _notifEl.style.zIndex=10001;
    _notifEl.style.padding='10px 14px';
    _notifEl.style.borderRadius='10px';
    document.body.appendChild(_notifEl);
  }
  _notifEl.textContent = msg;
  _notifEl.style.display = 'block';
  _notifEl.style.border = type==='success' ? '1px solid #10b981' : type==='error' ? '1px solid #ef4444' : '1px solid #ccc';
  clearTimeout(_notifEl._t);
  _notifEl._t = setTimeout(()=>_notifEl.style.display='none', duration);
}

// Cleanup listeners on unload
window.addEventListener('beforeunload', ()=>{
  if (window.solana && window.solana.removeEventListener) window.solana.removeEventListener('disconnect', handlePhantomDisconnect);
  closeModal();
});

// expose functions globally used in templates
window.connectPhantomWallet = connectPhantomWallet;
window.disconnectWallet = function(){ if (window.solana?.disconnect) window.solana.disconnect(); handlePhantomDisconnect(); };
window.buyToken = buyToken;
window.sellToken = sellToken;
