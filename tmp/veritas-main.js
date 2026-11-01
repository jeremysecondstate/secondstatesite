/**
*  Ajax Autocomplete for jQuery, version 1.4.7
*  (c) 2017 Tomas Kirda
*
*  Ajax Autocomplete for jQuery is freely distributable under the terms of an MIT-style license.
*  For details, see the web site: https://github.com/devbridge/jQuery-Autocomplete
*/
!function(a){"use strict";"function"==typeof define&&define.amd?define(["jquery"],a):a("object"==typeof exports&&"function"==typeof require?require("jquery"):jQuery)}(function(a){"use strict";function b(c,d){var e=this;e.element=c,e.el=a(c),e.suggestions=[],e.badQueries=[],e.selectedIndex=-1,e.currentValue=e.element.value,e.timeoutId=null,e.cachedResponse={},e.onChangeTimeout=null,e.onChange=null,e.isLocal=!1,e.suggestionsContainer=null,e.noSuggestionsContainer=null,e.options=a.extend({},b.defaults,d),e.classes={selected:"autocomplete-selected",suggestion:"autocomplete-suggestion"},e.hint=null,e.hintValue="",e.selection=null,e.initialize(),e.setOptions(d)}function c(a,b,c){return a.value.toLowerCase().indexOf(c)!==-1}function d(b){return"string"==typeof b?a.parseJSON(b):b}function e(a,b){if(!b)return a.value;var c="("+g.escapeRegExChars(b)+")";return a.value.replace(new RegExp(c,"gi"),"<strong>$1</strong>").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/&lt;(\/?strong)&gt;/g,"<$1>")}function f(a,b){return'<div class="autocomplete-group">'+b+"</div>"}var g=function(){return{escapeRegExChars:function(a){return a.replace(/[|\\{}()[\]^$+*?.]/g,"\\$&")},createNode:function(a){var b=document.createElement("div");return b.className=a,b.style.position="absolute",b.style.display="none",b}}}(),h={ESC:27,TAB:9,RETURN:13,LEFT:37,UP:38,RIGHT:39,DOWN:40},i=a.noop;b.utils=g,a.Autocomplete=b,b.defaults={ajaxSettings:{},autoSelectFirst:!1,appendTo:"body",serviceUrl:null,lookup:null,onSelect:null,width:"auto",minChars:1,maxHeight:300,deferRequestBy:0,params:{},formatResult:e,formatGroup:f,delimiter:null,zIndex:9999,type:"GET",noCache:!1,onSearchStart:i,onSearchComplete:i,onSearchError:i,preserveInput:!1,containerClass:"autocomplete-suggestions",tabDisabled:!1,dataType:"text",currentRequest:null,triggerSelectOnValidInput:!0,preventBadQueries:!0,lookupFilter:c,paramName:"query",transformResult:d,showNoSuggestionNotice:!1,noSuggestionNotice:"No results",orientation:"bottom",forceFixPosition:!1},b.prototype={initialize:function(){var c,d=this,e="."+d.classes.suggestion,f=d.classes.selected,g=d.options;d.element.setAttribute("autocomplete","off"),d.noSuggestionsContainer=a('<div class="autocomplete-no-suggestion"></div>').html(this.options.noSuggestionNotice).get(0),d.suggestionsContainer=b.utils.createNode(g.containerClass),c=a(d.suggestionsContainer),c.appendTo(g.appendTo||"body"),"auto"!==g.width&&c.css("width",g.width),c.on("mouseover.autocomplete",e,function(){d.activate(a(this).data("index"))}),c.on("mouseout.autocomplete",function(){d.selectedIndex=-1,c.children("."+f).removeClass(f)}),c.on("click.autocomplete",e,function(){d.select(a(this).data("index"))}),c.on("click.autocomplete",function(){clearTimeout(d.blurTimeoutId)}),d.fixPositionCapture=function(){d.visible&&d.fixPosition()},a(window).on("resize.autocomplete",d.fixPositionCapture),d.el.on("keydown.autocomplete",function(a){d.onKeyPress(a)}),d.el.on("keyup.autocomplete",function(a){d.onKeyUp(a)}),d.el.on("blur.autocomplete",function(){d.onBlur()}),d.el.on("focus.autocomplete",function(){d.onFocus()}),d.el.on("change.autocomplete",function(a){d.onKeyUp(a)}),d.el.on("input.autocomplete",function(a){d.onKeyUp(a)})},onFocus:function(){var a=this;a.fixPosition(),a.el.val().length>=a.options.minChars&&a.onValueChange()},onBlur:function(){var a=this;a.blurTimeoutId=setTimeout(function(){a.hide()},200)},abortAjax:function(){var a=this;a.currentRequest&&(a.currentRequest.abort(),a.currentRequest=null)},setOptions:function(b){var c=this,d=a.extend({},c.options,b);c.isLocal=Array.isArray(d.lookup),c.isLocal&&(d.lookup=c.verifySuggestionsFormat(d.lookup)),d.orientation=c.validateOrientation(d.orientation,"bottom"),a(c.suggestionsContainer).css({"max-height":d.maxHeight+"px",width:d.width+"px","z-index":d.zIndex}),this.options=d},clearCache:function(){this.cachedResponse={},this.badQueries=[]},clear:function(){this.clearCache(),this.currentValue="",this.suggestions=[]},disable:function(){var a=this;a.disabled=!0,clearTimeout(a.onChangeTimeout),a.abortAjax()},enable:function(){this.disabled=!1},fixPosition:function(){var b=this,c=a(b.suggestionsContainer),d=c.parent().get(0);if(d===document.body||b.options.forceFixPosition){var e=b.options.orientation,f=c.outerHeight(),g=b.el.outerHeight(),h=b.el.offset(),i={top:h.top,left:h.left};if("auto"===e){var j=a(window).height(),k=a(window).scrollTop(),l=-k+h.top-f,m=k+j-(h.top+g+f);e=Math.max(l,m)===l?"top":"bottom"}if("top"===e?i.top+=-f:i.top+=g,d!==document.body){var n,o=c.css("opacity");b.visible||c.css("opacity",0).show(),n=c.offsetParent().offset(),i.top-=n.top,i.top+=d.scrollTop,i.left-=n.left,b.visible||c.css("opacity",o).hide()}"auto"===b.options.width&&(i.width=b.el.outerWidth()+"px"),c.css(i)}},isCursorAtEnd:function(){var a,b=this,c=b.el.val().length,d=b.element.selectionStart;return"number"==typeof d?d===c:!document.selection||(a=document.selection.createRange(),a.moveStart("character",-c),c===a.text.length)},onKeyPress:function(a){var b=this;if(!b.disabled&&!b.visible&&a.which===h.DOWN&&b.currentValue)return void b.suggest();if(!b.disabled&&b.visible){switch(a.which){case h.ESC:b.el.val(b.currentValue),b.hide();break;case h.RIGHT:if(b.hint&&b.options.onHint&&b.isCursorAtEnd()){b.selectHint();break}return;case h.TAB:if(b.hint&&b.options.onHint)return void b.selectHint();if(b.selectedIndex===-1)return void b.hide();if(b.select(b.selectedIndex),b.options.tabDisabled===!1)return;break;case h.RETURN:if(b.selectedIndex===-1)return void b.hide();b.select(b.selectedIndex);break;case h.UP:b.moveUp();break;case h.DOWN:b.moveDown();break;default:return}a.stopImmediatePropagation(),a.preventDefault()}},onKeyUp:function(a){var b=this;if(!b.disabled){switch(a.which){case h.UP:case h.DOWN:return}clearTimeout(b.onChangeTimeout),b.currentValue!==b.el.val()&&(b.findBestHint(),b.options.deferRequestBy>0?b.onChangeTimeout=setTimeout(function(){b.onValueChange()},b.options.deferRequestBy):b.onValueChange())}},onValueChange:function(){if(this.ignoreValueChange)return void(this.ignoreValueChange=!1);var b=this,c=b.options,d=b.el.val(),e=b.getQuery(d);return b.selection&&b.currentValue!==e&&(b.selection=null,(c.onInvalidateSelection||a.noop).call(b.element)),clearTimeout(b.onChangeTimeout),b.currentValue=d,b.selectedIndex=-1,c.triggerSelectOnValidInput&&b.isExactMatch(e)?void b.select(0):void(e.length<c.minChars?b.hide():b.getSuggestions(e))},isExactMatch:function(a){var b=this.suggestions;return 1===b.length&&b[0].value.toLowerCase()===a.toLowerCase()},getQuery:function(b){var c,d=this.options.delimiter;return d?(c=b.split(d),a.trim(c[c.length-1])):b},getSuggestionsLocal:function(b){var c,d=this,e=d.options,f=b.toLowerCase(),g=e.lookupFilter,h=parseInt(e.lookupLimit,10);return c={suggestions:a.grep(e.lookup,function(a){return g(a,b,f)})},h&&c.suggestions.length>h&&(c.suggestions=c.suggestions.slice(0,h)),c},getSuggestions:function(b){var c,d,e,f,g=this,h=g.options,i=h.serviceUrl;if(h.params[h.paramName]=b,h.onSearchStart.call(g.element,h.params)!==!1){if(d=h.ignoreParams?null:h.params,a.isFunction(h.lookup))return void h.lookup(b,function(a){g.suggestions=a.suggestions,g.suggest(),h.onSearchComplete.call(g.element,b,a.suggestions)});g.isLocal?c=g.getSuggestionsLocal(b):(a.isFunction(i)&&(i=i.call(g.element,b)),e=i+"?"+a.param(d||{}),c=g.cachedResponse[e]),c&&Array.isArray(c.suggestions)?(g.suggestions=c.suggestions,g.suggest(),h.onSearchComplete.call(g.element,b,c.suggestions)):g.isBadQuery(b)?h.onSearchComplete.call(g.element,b,[]):(g.abortAjax(),f={url:i,data:d,type:h.type,dataType:h.dataType},a.extend(f,h.ajaxSettings),g.currentRequest=a.ajax(f).done(function(a){var c;g.currentRequest=null,c=h.transformResult(a,b),g.processResponse(c,b,e),h.onSearchComplete.call(g.element,b,c.suggestions)}).fail(function(a,c,d){h.onSearchError.call(g.element,b,a,c,d)}))}},isBadQuery:function(a){if(!this.options.preventBadQueries)return!1;for(var b=this.badQueries,c=b.length;c--;)if(0===a.indexOf(b[c]))return!0;return!1},hide:function(){var b=this,c=a(b.suggestionsContainer);a.isFunction(b.options.onHide)&&b.visible&&b.options.onHide.call(b.element,c),b.visible=!1,b.selectedIndex=-1,clearTimeout(b.onChangeTimeout),a(b.suggestionsContainer).hide(),b.signalHint(null)},suggest:function(){if(!this.suggestions.length)return void(this.options.showNoSuggestionNotice?this.noSuggestions():this.hide());var b,c=this,d=c.options,e=d.groupBy,f=d.formatResult,g=c.getQuery(c.currentValue),h=c.classes.suggestion,i=c.classes.selected,j=a(c.suggestionsContainer),k=a(c.noSuggestionsContainer),l=d.beforeRender,m="",n=function(a,c){var f=a.data[e];return b===f?"":(b=f,d.formatGroup(a,b))};return d.triggerSelectOnValidInput&&c.isExactMatch(g)?void c.select(0):(a.each(c.suggestions,function(a,b){e&&(m+=n(b,g,a)),m+='<div class="'+h+'" data-index="'+a+'">'+f(b,g,a)+"</div>"}),this.adjustContainerWidth(),k.detach(),j.html(m),a.isFunction(l)&&l.call(c.element,j,c.suggestions),c.fixPosition(),j.show(),d.autoSelectFirst&&(c.selectedIndex=0,j.scrollTop(0),j.children("."+h).first().addClass(i)),c.visible=!0,void c.findBestHint())},noSuggestions:function(){var b=this,c=b.options.beforeRender,d=a(b.suggestionsContainer),e=a(b.noSuggestionsContainer);this.adjustContainerWidth(),e.detach(),d.empty(),d.append(e),a.isFunction(c)&&c.call(b.element,d,b.suggestions),b.fixPosition(),d.show(),b.visible=!0},adjustContainerWidth:function(){var b,c=this,d=c.options,e=a(c.suggestionsContainer);"auto"===d.width?(b=c.el.outerWidth(),e.css("width",b>0?b:300)):"flex"===d.width&&e.css("width","")},findBestHint:function(){var b=this,c=b.el.val().toLowerCase(),d=null;c&&(a.each(b.suggestions,function(a,b){var e=0===b.value.toLowerCase().indexOf(c);return e&&(d=b),!e}),b.signalHint(d))},signalHint:function(b){var c="",d=this;b&&(c=d.currentValue+b.value.substr(d.currentValue.length)),d.hintValue!==c&&(d.hintValue=c,d.hint=b,(this.options.onHint||a.noop)(c))},verifySuggestionsFormat:function(b){return b.length&&"string"==typeof b[0]?a.map(b,function(a){return{value:a,data:null}}):b},validateOrientation:function(b,c){return b=a.trim(b||"").toLowerCase(),a.inArray(b,["auto","bottom","top"])===-1&&(b=c),b},processResponse:function(a,b,c){var d=this,e=d.options;a.suggestions=d.verifySuggestionsFormat(a.suggestions),e.noCache||(d.cachedResponse[c]=a,e.preventBadQueries&&!a.suggestions.length&&d.badQueries.push(b)),b===d.getQuery(d.currentValue)&&(d.suggestions=a.suggestions,d.suggest())},activate:function(b){var c,d=this,e=d.classes.selected,f=a(d.suggestionsContainer),g=f.find("."+d.classes.suggestion);return f.find("."+e).removeClass(e),d.selectedIndex=b,d.selectedIndex!==-1&&g.length>d.selectedIndex?(c=g.get(d.selectedIndex),a(c).addClass(e),c):null},selectHint:function(){var b=this,c=a.inArray(b.hint,b.suggestions);b.select(c)},select:function(a){var b=this;b.hide(),b.onSelect(a)},moveUp:function(){var b=this;if(b.selectedIndex!==-1)return 0===b.selectedIndex?(a(b.suggestionsContainer).children("."+b.classes.suggestion).first().removeClass(b.classes.selected),b.selectedIndex=-1,b.ignoreValueChange=!1,b.el.val(b.currentValue),void b.findBestHint()):void b.adjustScroll(b.selectedIndex-1)},moveDown:function(){var a=this;a.selectedIndex!==a.suggestions.length-1&&a.adjustScroll(a.selectedIndex+1)},adjustScroll:function(b){var c=this,d=c.activate(b);if(d){var e,f,g,h=a(d).outerHeight();e=d.offsetTop,f=a(c.suggestionsContainer).scrollTop(),g=f+c.options.maxHeight-h,e<f?a(c.suggestionsContainer).scrollTop(e):e>g&&a(c.suggestionsContainer).scrollTop(e-c.options.maxHeight+h),c.options.preserveInput||(c.ignoreValueChange=!0,c.el.val(c.getValue(c.suggestions[b].value))),c.signalHint(null)}},onSelect:function(b){var c=this,d=c.options.onSelect,e=c.suggestions[b];c.currentValue=c.getValue(e.value),c.currentValue===c.el.val()||c.options.preserveInput||c.el.val(c.currentValue),c.signalHint(null),c.suggestions=[],c.selection=e,a.isFunction(d)&&d.call(c.element,e)},getValue:function(a){var b,c,d=this,e=d.options.delimiter;return e?(b=d.currentValue,c=b.split(e),1===c.length?a:b.substr(0,b.length-c[c.length-1].length)+a):a},dispose:function(){var b=this;b.el.off(".autocomplete").removeData("autocomplete"),a(window).off("resize.autocomplete",b.fixPositionCapture),a(b.suggestionsContainer).remove()}},a.fn.devbridgeAutocomplete=function(c,d){var e="autocomplete";return arguments.length?this.each(function(){var f=a(this),g=f.data(e);"string"==typeof c?g&&"function"==typeof g[c]&&g[c](d):(g&&g.dispose&&g.dispose(),g=new b(this,c),f.data(e,g))}):this.first().data(e)},a.fn.autocomplete||(a.fn.autocomplete=a.fn.devbridgeAutocomplete)});
/*!
	Zoom 1.7.20
	license: MIT
	http://www.jacklmoore.com/zoom
*/
(function(o){var t={url:!1,callback:!1,target:!1,duration:120,on:"mouseover",touch:!0,onZoomIn:!1,onZoomOut:!1,magnify:1};o.zoom=function(t,n,e,i){var u,c,r,a,m,l,s,f=o(t),h=f.css("position"),d=o(n);return t.style.position=/(absolute|fixed)/.test(h)?h:"relative",t.style.overflow="hidden",e.style.width=e.style.height="",o(e).addClass("zoomImg").css({position:"absolute",top:0,left:0,opacity:0,width:e.width*i,height:e.height*i,border:"none",maxWidth:"none",maxHeight:"none"}).appendTo(t),{init:function(){c=f.outerWidth(),u=f.outerHeight(),n===t?(a=c,r=u):(a=d.outerWidth(),r=d.outerHeight()),m=(e.width-c)/a,l=(e.height-u)/r,s=d.offset()},move:function(o){var t=o.pageX-s.left,n=o.pageY-s.top;n=Math.max(Math.min(n,r),0),t=Math.max(Math.min(t,a),0),e.style.left=t*-m+"px",e.style.top=n*-l+"px"}}},o.fn.zoom=function(n){return this.each(function(){var e=o.extend({},t,n||{}),i=e.target&&o(e.target)[0]||this,u=this,c=o(u),r=document.createElement("img"),a=o(r),m="mousemove.zoom",l=!1,s=!1;if(!e.url){var f=u.querySelector("img");if(f&&(e.url=f.getAttribute("data-src")||f.currentSrc||f.src),!e.url)return}c.one("zoom.destroy",function(o,t){c.off(".zoom"),i.style.position=o,i.style.overflow=t,r.onload=null,a.remove()}.bind(this,i.style.position,i.style.overflow)),r.onload=function(){function t(t){f.init(),f.move(t),a.stop().fadeTo(o.support.opacity?e.duration:0,1,o.isFunction(e.onZoomIn)?e.onZoomIn.call(r):!1)}function n(){a.stop().fadeTo(e.duration,0,o.isFunction(e.onZoomOut)?e.onZoomOut.call(r):!1)}var f=o.zoom(i,u,r,e.magnify);"grab"===e.on?c.on("mousedown.zoom",function(e){1===e.which&&(o(document).one("mouseup.zoom",function(){n(),o(document).off(m,f.move)}),t(e),o(document).on(m,f.move),e.preventDefault())}):"click"===e.on?c.on("click.zoom",function(e){return l?void 0:(l=!0,t(e),o(document).on(m,f.move),o(document).one("click.zoom",function(){n(),l=!1,o(document).off(m,f.move)}),!1)}):"toggle"===e.on?c.on("click.zoom",function(o){l?n():t(o),l=!l}):"mouseover"===e.on&&(f.init(),c.on("mouseenter.zoom",t).on("mouseleave.zoom",n).on(m,f.move)),e.touch&&c.on("touchstart.zoom",function(o){o.preventDefault(),s?(s=!1,n()):(s=!0,t(o.originalEvent.touches[0]||o.originalEvent.changedTouches[0]))}).on("touchmove.zoom",function(o){o.preventDefault(),f.move(o.originalEvent.touches[0]||o.originalEvent.changedTouches[0])}).on("touchend.zoom",function(o){o.preventDefault(),s&&(s=!1,n())}),o.isFunction(e.callback)&&e.callback.call(r)},r.setAttribute("role","presentation"),r.src=e.url})},o.fn.zoom.defaults=t})(window.jQuery);
// jQuery Mask Plugin v1.14.13
// github.com/igorescobar/jQuery-Mask-Plugin
var $jscomp={scope:{},findInternal:function(a,l,d){a instanceof String&&(a=String(a));for(var p=a.length,h=0;h<p;h++){var b=a[h];if(l.call(d,b,h,a))return{i:h,v:b}}return{i:-1,v:void 0}}};$jscomp.defineProperty="function"==typeof Object.defineProperties?Object.defineProperty:function(a,l,d){if(d.get||d.set)throw new TypeError("ES3 does not support getters and setters.");a!=Array.prototype&&a!=Object.prototype&&(a[l]=d.value)};
$jscomp.getGlobal=function(a){return"undefined"!=typeof window&&window===a?a:"undefined"!=typeof global&&null!=global?global:a};$jscomp.global=$jscomp.getGlobal(this);$jscomp.polyfill=function(a,l,d,p){if(l){d=$jscomp.global;a=a.split(".");for(p=0;p<a.length-1;p++){var h=a[p];h in d||(d[h]={});d=d[h]}a=a[a.length-1];p=d[a];l=l(p);l!=p&&null!=l&&$jscomp.defineProperty(d,a,{configurable:!0,writable:!0,value:l})}};
$jscomp.polyfill("Array.prototype.find",function(a){return a?a:function(a,d){return $jscomp.findInternal(this,a,d).v}},"es6-impl","es3");
(function(a,l,d){"function"===typeof define&&define.amd?define(["jquery"],a):"object"===typeof exports?module.exports=a(require("jquery")):a(l||d)})(function(a){var l=function(b,e,f){var c={invalid:[],getCaret:function(){try{var a,r=0,g=b.get(0),e=document.selection,f=g.selectionStart;if(e&&-1===navigator.appVersion.indexOf("MSIE 10"))a=e.createRange(),a.moveStart("character",-c.val().length),r=a.text.length;else if(f||"0"===f)r=f;return r}catch(C){}},setCaret:function(a){try{if(b.is(":focus")){var c,
g=b.get(0);g.setSelectionRange?g.setSelectionRange(a,a):(c=g.createTextRange(),c.collapse(!0),c.moveEnd("character",a),c.moveStart("character",a),c.select())}}catch(B){}},events:function(){b.on("keydown.mask",function(a){b.data("mask-keycode",a.keyCode||a.which);b.data("mask-previus-value",b.val());b.data("mask-previus-caret-pos",c.getCaret());c.maskDigitPosMapOld=c.maskDigitPosMap}).on(a.jMaskGlobals.useInput?"input.mask":"keyup.mask",c.behaviour).on("paste.mask drop.mask",function(){setTimeout(function(){b.keydown().keyup()},
100)}).on("change.mask",function(){b.data("changed",!0)}).on("blur.mask",function(){d===c.val()||b.data("changed")||b.trigger("change");b.data("changed",!1)}).on("blur.mask",function(){d=c.val()}).on("focus.mask",function(b){!0===f.selectOnFocus&&a(b.target).select()}).on("focusout.mask",function(){f.clearIfNotMatch&&!h.test(c.val())&&c.val("")})},getRegexMask:function(){for(var a=[],b,c,f,n,d=0;d<e.length;d++)(b=m.translation[e.charAt(d)])?(c=b.pattern.toString().replace(/.{1}$|^.{1}/g,""),f=b.optional,
(b=b.recursive)?(a.push(e.charAt(d)),n={digit:e.charAt(d),pattern:c}):a.push(f||b?c+"?":c)):a.push(e.charAt(d).replace(/[-\/\\^$*+?.()|[\]{}]/g,"\\$&"));a=a.join("");n&&(a=a.replace(new RegExp("("+n.digit+"(.*"+n.digit+")?)"),"($1)?").replace(new RegExp(n.digit,"g"),n.pattern));return new RegExp(a)},destroyEvents:function(){b.off("input keydown keyup paste drop blur focusout ".split(" ").join(".mask "))},val:function(a){var c=b.is("input")?"val":"text";if(0<arguments.length){if(b[c]()!==a)b[c](a);
c=b}else c=b[c]();return c},calculateCaretPosition:function(){var a=b.data("mask-previus-value")||"",e=c.getMasked(),g=c.getCaret();if(a!==e){var f=b.data("mask-previus-caret-pos")||0,e=e.length,d=a.length,m=a=0,h=0,l=0,k;for(k=g;k<e&&c.maskDigitPosMap[k];k++)m++;for(k=g-1;0<=k&&c.maskDigitPosMap[k];k--)a++;for(k=g-1;0<=k;k--)c.maskDigitPosMap[k]&&h++;for(k=f-1;0<=k;k--)c.maskDigitPosMapOld[k]&&l++;g>d?g=10*e:f>=g&&f!==d?c.maskDigitPosMapOld[g]||(f=g,g=g-(l-h)-a,c.maskDigitPosMap[g]&&(g=f)):g>f&&
(g=g+(h-l)+m)}return g},behaviour:function(f){f=f||window.event;c.invalid=[];var e=b.data("mask-keycode");if(-1===a.inArray(e,m.byPassKeys)){var e=c.getMasked(),g=c.getCaret();setTimeout(function(){c.setCaret(c.calculateCaretPosition())},10);c.val(e);c.setCaret(g);return c.callbacks(f)}},getMasked:function(a,b){var g=[],d=void 0===b?c.val():b+"",n=0,h=e.length,q=0,l=d.length,k=1,r="push",p=-1,t=0,y=[],v,z;f.reverse?(r="unshift",k=-1,v=0,n=h-1,q=l-1,z=function(){return-1<n&&-1<q}):(v=h-1,z=function(){return n<
h&&q<l});for(var A;z();){var x=e.charAt(n),w=d.charAt(q),u=m.translation[x];if(u)w.match(u.pattern)?(g[r](w),u.recursive&&(-1===p?p=n:n===v&&n!==p&&(n=p-k),v===p&&(n-=k)),n+=k):w===A?(t--,A=void 0):u.optional?(n+=k,q-=k):u.fallback?(g[r](u.fallback),n+=k,q-=k):c.invalid.push({p:q,v:w,e:u.pattern}),q+=k;else{if(!a)g[r](x);w===x?(y.push(q),q+=k):(A=x,y.push(q+t),t++);n+=k}}d=e.charAt(v);h!==l+1||m.translation[d]||g.push(d);g=g.join("");c.mapMaskdigitPositions(g,y,l);return g},mapMaskdigitPositions:function(a,
b,e){a=f.reverse?a.length-e:0;c.maskDigitPosMap={};for(e=0;e<b.length;e++)c.maskDigitPosMap[b[e]+a]=1},callbacks:function(a){var h=c.val(),g=h!==d,m=[h,a,b,f],q=function(a,b,c){"function"===typeof f[a]&&b&&f[a].apply(this,c)};q("onChange",!0===g,m);q("onKeyPress",!0===g,m);q("onComplete",h.length===e.length,m);q("onInvalid",0<c.invalid.length,[h,a,b,c.invalid,f])}};b=a(b);var m=this,d=c.val(),h;e="function"===typeof e?e(c.val(),void 0,b,f):e;m.mask=e;m.options=f;m.remove=function(){var a=c.getCaret();
c.destroyEvents();c.val(m.getCleanVal());c.setCaret(a);return b};m.getCleanVal=function(){return c.getMasked(!0)};m.getMaskedVal=function(a){return c.getMasked(!1,a)};m.init=function(d){d=d||!1;f=f||{};m.clearIfNotMatch=a.jMaskGlobals.clearIfNotMatch;m.byPassKeys=a.jMaskGlobals.byPassKeys;m.translation=a.extend({},a.jMaskGlobals.translation,f.translation);m=a.extend(!0,{},m,f);h=c.getRegexMask();if(d)c.events(),c.val(c.getMasked());else{f.placeholder&&b.attr("placeholder",f.placeholder);b.data("mask")&&
b.attr("autocomplete","off");d=0;for(var l=!0;d<e.length;d++){var g=m.translation[e.charAt(d)];if(g&&g.recursive){l=!1;break}}l&&b.attr("maxlength",e.length);c.destroyEvents();c.events();d=c.getCaret();c.val(c.getMasked());c.setCaret(d)}};m.init(!b.is("input"))};a.maskWatchers={};var d=function(){var b=a(this),e={},f=b.attr("data-mask");b.attr("data-mask-reverse")&&(e.reverse=!0);b.attr("data-mask-clearifnotmatch")&&(e.clearIfNotMatch=!0);"true"===b.attr("data-mask-selectonfocus")&&(e.selectOnFocus=
!0);if(p(b,f,e))return b.data("mask",new l(this,f,e))},p=function(b,e,f){f=f||{};var c=a(b).data("mask"),d=JSON.stringify;b=a(b).val()||a(b).text();try{return"function"===typeof e&&(e=e(b)),"object"!==typeof c||d(c.options)!==d(f)||c.mask!==e}catch(t){}},h=function(a){var b=document.createElement("div"),d;a="on"+a;d=a in b;d||(b.setAttribute(a,"return;"),d="function"===typeof b[a]);return d};a.fn.mask=function(b,d){d=d||{};var e=this.selector,c=a.jMaskGlobals,h=c.watchInterval,c=d.watchInputs||c.watchInputs,
t=function(){if(p(this,b,d))return a(this).data("mask",new l(this,b,d))};a(this).each(t);e&&""!==e&&c&&(clearInterval(a.maskWatchers[e]),a.maskWatchers[e]=setInterval(function(){a(document).find(e).each(t)},h));return this};a.fn.masked=function(a){return this.data("mask").getMaskedVal(a)};a.fn.unmask=function(){clearInterval(a.maskWatchers[this.selector]);delete a.maskWatchers[this.selector];return this.each(function(){var b=a(this).data("mask");b&&b.remove().removeData("mask")})};a.fn.cleanVal=function(){return this.data("mask").getCleanVal()};
a.applyDataMask=function(b){b=b||a.jMaskGlobals.maskElements;(b instanceof a?b:a(b)).filter(a.jMaskGlobals.dataMaskAttr).each(d)};h={maskElements:"input,td,span,div",dataMaskAttr:"*[data-mask]",dataMask:!0,watchInterval:300,watchInputs:!0,useInput:!/Chrome\/[2-4][0-9]|SamsungBrowser/.test(window.navigator.userAgent)&&h("input"),watchDataMask:!1,byPassKeys:[9,16,17,18,36,37,38,39,40,91],translation:{0:{pattern:/\d/},9:{pattern:/\d/,optional:!0},"#":{pattern:/\d/,recursive:!0},A:{pattern:/[a-zA-Z0-9]/},
S:{pattern:/[a-zA-Z]/}}};a.jMaskGlobals=a.jMaskGlobals||{};h=a.jMaskGlobals=a.extend(!0,{},h,a.jMaskGlobals);h.dataMask&&a.applyDataMask();setInterval(function(){a.jMaskGlobals.watchDataMask&&a.applyDataMask()},h.watchInterval)},window.jQuery,window.Zepto);

/*! UIkit 3.22.0 | https://www.getuikit.com | (c) 2014 - 2025 YOOtheme | MIT License */(function($e,ye){typeof exports=="object"&&typeof module<"u"?module.exports=ye():typeof define=="function"&&define.amd?define("uikit",ye):($e=typeof globalThis<"u"?globalThis:$e||self,$e.UIkit=ye())})(this,function(){"use strict";const{hasOwnProperty:$e,toString:ye}=Object.prototype;function gt(t,e){return $e.call(t,e)}const nr=/\B([A-Z])/g,Bt=ct(t=>t.replace(nr,"-$1").toLowerCase()),or=/-(\w)/g,ke=ct(t=>(t.charAt(0).toLowerCase()+t.slice(1)).replace(or,(e,i)=>i.toUpperCase())),Nt=ct(t=>t.charAt(0).toUpperCase()+t.slice(1));function mt(t,e){var i;return(i=t==null?void 0:t.startsWith)==null?void 0:i.call(t,e)}function ee(t,e){var i;return(i=t==null?void 0:t.endsWith)==null?void 0:i.call(t,e)}function b(t,e){var i;return(i=t==null?void 0:t.includes)==null?void 0:i.call(t,e)}function xt(t,e){var i;return(i=t==null?void 0:t.findIndex)==null?void 0:i.call(t,e)}const{isArray:J,from:ie}=Array,{assign:ft}=Object;function nt(t){return typeof t=="function"}function Tt(t){return t!==null&&typeof t=="object"}function Se(t){return ye.call(t)==="[object Object]"}function Qe(t){return Tt(t)&&t===t.window}function Ie(t){return Hi(t)===9}function Te(t){return Hi(t)>=1}function se(t){return Hi(t)===1}function Hi(t){return!Qe(t)&&Tt(t)&&t.nodeType}function ne(t){return typeof t=="boolean"}function F(t){return typeof t=="string"}function Ee(t){return typeof t=="number"}function vt(t){return Ee(t)||F(t)&&!isNaN(t-parseFloat(t))}function ti(t){return!(J(t)?t.length:Tt(t)&&Object.keys(t).length)}function X(t){return t===void 0}function Li(t){return ne(t)?t:t==="true"||t==="1"||t===""?!0:t==="false"||t==="0"?!1:t}function $t(t){const e=Number(t);return isNaN(e)?!1:e}function k(t){return parseFloat(t)||0}function R(t){return t&&T(t)[0]}function T(t){return Te(t)?[t]:Array.from(t||[]).filter(Te)}function zt(t){if(Qe(t))return t;t=R(t);const e=Ie(t)?t:t==null?void 0:t.ownerDocument;return(e==null?void 0:e.defaultView)||window}function Ce(t,e){return t===e||Tt(t)&&Tt(e)&&Object.keys(t).length===Object.keys(e).length&&oe(t,(i,s)=>i===e[s])}function Wi(t,e,i){return t.replace(new RegExp(`${e}|${i}`,"g"),s=>s===e?i:e)}function Ft(t){return t[t.length-1]}function oe(t,e){for(const i in t)if(e(t[i],i)===!1)return!1;return!0}function Rs(t,e){return t.slice().sort(({[e]:i=0},{[e]:s=0})=>i>s?1:s>i?-1:0)}function Ht(t,e){return t.reduce((i,s)=>i+k(nt(e)?e(s):s[e]),0)}function qs(t,e){const i=new Set;return t.filter(({[e]:s})=>i.has(s)?!1:i.add(s))}function ei(t,e){return e.reduce((i,s)=>({...i,[s]:t[s]}),{})}function K(t,e=0,i=1){return Math.min(Math.max($t(t)||0,e),i)}function A(){}function ii(...t){return[["bottom","top"],["right","left"]].every(([e,i])=>Math.min(...t.map(({[e]:s})=>s))-Math.max(...t.map(({[i]:s})=>s))>0)}function si(t,e){return t.x<=e.right&&t.x>=e.left&&t.y<=e.bottom&&t.y>=e.top}function ji(t,e,i){const s=e==="width"?"height":"width";return{[s]:t[e]?Math.round(i*t[s]/t[e]):t[s],[e]:i}}function Us(t,e){t={...t};for(const i in t)t=t[i]>e[i]?ji(t,i,e[i]):t;return t}function rr(t,e){t=Us(t,e);for(const i in t)t=t[i]<e[i]?ji(t,i,e[i]):t;return t}const Ri={ratio:ji,contain:Us,cover:rr};function ot(t,e,i=0,s=!1){e=T(e);const{length:n}=e;return n?(t=vt(t)?$t(t):t==="next"?i+1:t==="previous"?i-1:t==="last"?n-1:e.indexOf(R(t)),s?K(t,0,n-1):(t%=n,t<0?t+n:t)):-1}function ct(t){const e=Object.create(null);return(i,...s)=>e[i]||(e[i]=t(i,...s))}function S(t,...e){for(const i of T(t)){const s=Lt(e).filter(n=>!x(i,n));s.length&&i.classList.add(...s)}}function _(t,...e){for(const i of T(t)){const s=Lt(e).filter(n=>x(i,n));s.length&&i.classList.remove(...s)}}function ni(t,e,i){i=Lt(i),e=Lt(e).filter(s=>!b(i,s)),_(t,e),S(t,i)}function x(t,e){return[e]=Lt(e),T(t).some(i=>i.classList.contains(e))}function H(t,e,i){const s=Lt(e);X(i)||(i=!!i);for(const n of T(t))for(const o of s)n.classList.toggle(o,i)}function Lt(t){return t?J(t)?t.map(Lt).flat():String(t).split(" ").filter(Boolean):[]}function p(t,e,i){var s;if(Tt(e)){for(const n in e)p(t,n,e[n]);return}if(X(i))return(s=R(t))==null?void 0:s.getAttribute(e);for(const n of T(t))nt(i)&&(i=i.call(n,p(n,e))),i===null?Pe(n,e):n.setAttribute(e,i)}function Et(t,e){return T(t).some(i=>i.hasAttribute(e))}function Pe(t,e){T(t).forEach(i=>i.removeAttribute(e))}function Z(t,e){for(const i of[e,`data-${e}`])if(Et(t,i))return p(t,i)}const Wt=typeof window<"u",U=Wt&&document.dir==="rtl",re=Wt&&"ontouchstart"in window,ae=Wt&&window.PointerEvent,ut=ae?"pointerdown":re?"touchstart":"mousedown",oi=ae?"pointermove":re?"touchmove":"mousemove",Ct=ae?"pointerup":re?"touchend":"mouseup",jt=ae?"pointerenter":re?"":"mouseenter",le=ae?"pointerleave":re?"":"mouseleave",ri=ae?"pointercancel":"touchcancel",ar={area:!0,base:!0,br:!0,col:!0,embed:!0,hr:!0,img:!0,input:!0,keygen:!0,link:!0,meta:!0,param:!0,source:!0,track:!0,wbr:!0};function qi(t){return T(t).some(e=>ar[e.tagName.toLowerCase()])}const lr=Wt&&Element.prototype.checkVisibility||function(){return this.offsetWidth||this.offsetHeight||this.getClientRects().length};function q(t){return T(t).some(e=>lr.call(e))}const _e="input,select,textarea,button";function ai(t){return T(t).some(e=>C(e,_e))}const Ae=`${_e},a[href],[tabindex]`;function li(t){return C(t,Ae)}function O(t){var e;return(e=R(t))==null?void 0:e.parentElement}function Oe(t,e){return T(t).filter(i=>C(i,e))}function C(t,e){return T(t).some(i=>i.matches(e))}function he(t,e){const i=[];for(;t=O(t);)(!e||C(t,e))&&i.push(t);return i}function B(t,e){t=R(t);const i=t?ie(t.children):[];return e?Oe(i,e):i}function yt(t,e){return e?T(t).indexOf(R(e)):B(O(t)).indexOf(t)}function ce(t){return t=R(t),t&&["origin","pathname","search"].every(e=>t[e]===location[e])}function Ui(t){if(ce(t)){const{hash:e,ownerDocument:i}=R(t),s=decodeURIComponent(e).slice(1);return s?i.getElementById(s)||i.getElementsByName(s)[0]:i.documentElement}}function tt(t,e){return Vi(t,Vs(t,e))}function De(t,e){return Me(t,Vs(t,e))}function Vi(t,e){return R(Xs(t,R(e),"querySelector"))}function Me(t,e){return T(Xs(t,R(e),"querySelectorAll"))}function Vs(t,e=document){return Ie(e)||Ys(t).isContextSelector?e:e.ownerDocument}const hr=/([!>+~-])(?=\s+[!>+~-]|\s*$)/g,cr=/(\([^)]*\)|[^,])+/g,Ys=ct(t=>{let e=!1;if(!t||!F(t))return{};const i=[];for(let s of t.match(cr))s=s.trim().replace(hr,"$1 *"),e||(e=["!","+","~","-",">"].includes(s[0])),i.push(s);return{selector:i.join(","),selectors:i,isContextSelector:e}}),ur=/(\([^)]*\)|\S)*/,Gs=ct(t=>{t=t.slice(1).trim();const[e]=t.match(ur);return[e,t.slice(e.length+1)]});function Xs(t,e=document,i){const s=Ys(t);if(!s.isContextSelector)return s.selector?Yi(e,i,s.selector):t;t="";const n=s.selectors.length===1;for(let o of s.selectors){let r,a=e;if(o[0]==="!"&&([r,o]=Gs(o),a=e.parentElement.closest(r),!o&&n)||a&&o[0]==="-"&&([r,o]=Gs(o),a=a.previousElementSibling,a=C(a,r)?a:null,!o&&n))return a;if(a){if(n)return o[0]==="~"||o[0]==="+"?(o=`:scope > :nth-child(${yt(a)+1}) ${o}`,a=a.parentElement):o[0]===">"&&(o=`:scope ${o}`),Yi(a,i,o);t+=`${t?",":""}${dr(a)} ${o}`}}return Ie(e)||(e=e.ownerDocument),Yi(e,i,t)}function Yi(t,e,i){try{return t[e](i)}catch{return null}}function dr(t){const e=[];for(;t.parentNode;){const i=p(t,"id");if(i){e.unshift(`#${Gi(i)}`);break}else{let{tagName:s}=t;s!=="HTML"&&(s+=`:nth-child(${yt(t)+1})`),e.unshift(s),t=t.parentNode}}return e.join(" > ")}function Gi(t){return F(t)?CSS.escape(t):""}function y(...t){let[e,i,s,n,o=!1]=Xi(t);n.length>1&&(n=pr(n)),o!=null&&o.self&&(n=gr(n)),s&&(n=fr(s,n));for(const r of i)for(const a of e)a.addEventListener(r,n,o);return()=>Rt(e,i,n,o)}function Rt(...t){let[e,i,,s,n=!1]=Xi(t);for(const o of i)for(const r of e)r.removeEventListener(o,s,n)}function L(...t){const[e,i,s,n,o=!1,r]=Xi(t),a=y(e,i,s,l=>{const c=!r||r(l);c&&(a(),n(l,c))},o);return a}function v(t,e,i){return Ji(t).every(s=>s.dispatchEvent(ue(e,!0,!0,i)))}function ue(t,e=!0,i=!1,s){return F(t)&&(t=new CustomEvent(t,{bubbles:e,cancelable:i,detail:s})),t}function Xi(t){return t[0]=Ji(t[0]),F(t[1])&&(t[1]=t[1].split(" ")),nt(t[2])&&t.splice(2,0,!1),t}function fr(t,e){return i=>{const s=t[0]===">"?Me(t,i.currentTarget).reverse().find(n=>n.contains(i.target)):i.target.closest(t);s&&(i.current=s,e.call(this,i),delete i.current)}}function pr(t){return e=>J(e.detail)?t(e,...e.detail):t(e)}function gr(t){return function(e){if(e.target===e.currentTarget||e.target===e.current)return t.call(null,e)}}function Js(t){return t&&"addEventListener"in t}function mr(t){return Js(t)?t:R(t)}function Ji(t){return J(t)?t.map(mr).filter(Boolean):F(t)?Me(t):Js(t)?[t]:T(t)}function pt(t){return t.pointerType==="touch"||!!t.touches}function kt(t){var e,i;const{clientX:s,clientY:n}=((e=t.touches)==null?void 0:e[0])||((i=t.changedTouches)==null?void 0:i[0])||t;return{x:s,y:n}}const vr={"animation-iteration-count":!0,"column-count":!0,"fill-opacity":!0,"flex-grow":!0,"flex-shrink":!0,"font-weight":!0,"line-height":!0,opacity:!0,order:!0,orphans:!0,"stroke-dasharray":!0,"stroke-dashoffset":!0,widows:!0,"z-index":!0,zoom:!0};function h(t,e,i,s){const n=T(t);for(const o of n)if(F(e)){if(e=hi(e),X(i))return getComputedStyle(o).getPropertyValue(e);o.style.setProperty(e,vt(i)&&!vr[e]?`${i}px`:i||Ee(i)?i:"",s)}else if(J(e)){const r={};for(const a of e)r[a]=h(o,a);return r}else if(Tt(e))for(const r in e)h(o,r,e[r],i);return n[0]}const hi=ct(t=>{if(mt(t,"--"))return t;t=Bt(t);const{style:e}=document.documentElement;if(t in e)return t;for(const i of["webkit","moz"]){const s=`-${i}-${t}`;if(s in e)return s}}),Ki="uk-transition",Zi="transitionend",Qi="transitioncanceled";function br(t,e,i=400,s="linear"){return i=Math.round(i),Promise.all(T(t).map(n=>new Promise((o,r)=>{for(const l in e)h(n,l);const a=setTimeout(()=>v(n,Zi),i);L(n,[Zi,Qi],({type:l})=>{clearTimeout(a),_(n,Ki),h(n,{transitionProperty:"",transitionDuration:"",transitionTimingFunction:""}),l===Qi?r():o(n)},{self:!0}),S(n,Ki),h(n,{transitionProperty:Object.keys(e).map(hi).join(","),transitionDuration:`${i}ms`,transitionTimingFunction:s,...e})})))}const N={start:br,async stop(t){v(t,Zi),await Promise.resolve()},async cancel(t){v(t,Qi),await Promise.resolve()},inProgress(t){return x(t,Ki)}},Be="uk-animation",Ks="animationend",ci="animationcanceled";function Zs(t,e,i=200,s,n){return Promise.all(T(t).map(o=>new Promise((r,a)=>{x(o,Be)&&v(o,ci);const l=[e,Be,`${Be}-${n?"leave":"enter"}`,s&&`uk-transform-origin-${s}`,n&&`${Be}-reverse`],c=setTimeout(()=>v(o,Ks),i);L(o,[Ks,ci],({type:u})=>{clearTimeout(c),u===ci?a():r(o),h(o,"animationDuration",""),_(o,l)},{self:!0}),h(o,"animationDuration",`${i}ms`),S(o,l)})))}const Pt={in:Zs,out(t,e,i,s){return Zs(t,e,i,s,!0)},inProgress(t){return x(t,Be)},cancel(t){v(t,ci)}};function wr(t){if(document.readyState!=="loading"){t();return}L(document,"DOMContentLoaded",t)}function z(t,...e){return e.some(i=>{var s;return((s=t==null?void 0:t.tagName)==null?void 0:s.toLowerCase())===i.toLowerCase()})}function Qs(t){return t=$(t),t&&(t.innerHTML=""),t}function bt(t,e){return X(e)?$(t).innerHTML:W(Qs(t),e)}const xr=fi("prepend"),W=fi("append"),ui=fi("before"),di=fi("after");function fi(t){return function(e,i){var s;const n=T(F(i)?St(i):i);return(s=$(e))==null||s[t](...n),tn(n)}}function Q(t){T(t).forEach(e=>e.remove())}function Ne(t,e){for(e=R(ui(t,e));e.firstElementChild;)e=e.firstElementChild;return W(e,t),e}function ts(t,e){return T(T(t).map(i=>i.hasChildNodes()?Ne(ie(i.childNodes),e):W(i,e)))}function ze(t){T(t).map(O).filter((e,i,s)=>s.indexOf(e)===i).forEach(e=>e.replaceWith(...e.childNodes))}const $r=/^<(\w+)\s*\/?>(?:<\/\1>)?$/;function St(t){const e=$r.exec(t);if(e)return document.createElement(e[1]);const i=document.createElement("template");return i.innerHTML=t.trim(),tn(i.content.childNodes)}function tn(t){return t.length>1?t:t[0]}function _t(t,e){if(se(t))for(e(t),t=t.firstElementChild;t;)_t(t,e),t=t.nextElementSibling}function $(t,e){return en(t)?R(St(t)):Vi(t,e)}function D(t,e){return en(t)?T(St(t)):Me(t,e)}function en(t){return F(t)&&mt(t.trim(),"<")}const qt={width:["left","right"],height:["top","bottom"]};function m(t){const e=se(t)?R(t).getBoundingClientRect():{height:et(t),width:pi(t),top:0,left:0};return{height:e.height,width:e.width,top:e.top,left:e.left,bottom:e.top+e.height,right:e.left+e.width}}function E(t,e){e&&h(t,{left:0,top:0});const i=m(t);if(t){const{scrollY:s,scrollX:n}=zt(t),o={height:s,width:n};for(const r in qt)for(const a of qt[r])i[a]+=o[r]}if(!e)return i;for(const s of["left","top"])h(t,s,e[s]-i[s])}function es(t){let{top:e,left:i}=E(t);const{ownerDocument:{body:s,documentElement:n},offsetParent:o}=R(t);let r=o||n;for(;r&&(r===s||r===n)&&h(r,"position")==="static";)r=r.parentNode;if(se(r)){const a=E(r);e-=a.top+k(h(r,"borderTopWidth")),i-=a.left+k(h(r,"borderLeftWidth"))}return{top:e-k(h(t,"marginTop")),left:i-k(h(t,"marginLeft"))}}function Fe(t){t=R(t);const e=[t.offsetTop,t.offsetLeft];for(;t=t.offsetParent;)if(e[0]+=t.offsetTop+k(h(t,"borderTopWidth")),e[1]+=t.offsetLeft+k(h(t,"borderLeftWidth")),h(t,"position")==="fixed"){const i=zt(t);return e[0]+=i.scrollY,e[1]+=i.scrollX,e}return e}const et=sn("height"),pi=sn("width");function sn(t){const e=Nt(t);return(i,s)=>{if(X(s)){if(Qe(i))return i[`inner${e}`];if(Ie(i)){const n=i.documentElement;return Math.max(n[`offset${e}`],n[`scroll${e}`])}return i=R(i),s=h(i,t),s=s==="auto"?i[`offset${e}`]:k(s)||0,s-de(i,t)}else return h(i,t,!s&&s!==0?"":+s+de(i,t)+"px")}}function de(t,e,i="border-box"){return h(t,"boxSizing")===i?Ht(qt[e],s=>k(h(t,`padding-${s}`))+k(h(t,`border-${s}-width`))):0}function gi(t){for(const e in qt)for(const i in qt[e])if(qt[e][i]===t)return qt[e][1-i];return t}function G(t,e="width",i=window,s=!1){return F(t)?Ht(kr(t),n=>{const o=Ir(n);return o?Tr(o==="vh"?Er():o==="vw"?pi(zt(i)):s?i[`offset${Nt(e)}`]:m(i)[e],n):n}):k(t)}const yr=/-?\d+(?:\.\d+)?(?:v[wh]|%|px)?/g,kr=ct(t=>t.toString().replace(/\s/g,"").match(yr)||[]),Sr=/(?:v[hw]|%)$/,Ir=ct(t=>(t.match(Sr)||[])[0]);function Tr(t,e){return t*k(e)/100}let He,fe;function Er(){return He||(fe||(fe=$("<div>"),h(fe,{height:"100vh",position:"fixed"}),y(window,"resize",()=>He=null)),W(document.body,fe),He=fe.clientHeight,Q(fe),He)}const At={read:Cr,write:Pr,clear:_r,flush:nn},mi=[],vi=[];function Cr(t){return mi.push(t),ss(),t}function Pr(t){return vi.push(t),ss(),t}function _r(t){rn(mi,t),rn(vi,t)}let is=!1;function nn(){on(mi),on(vi.splice(0)),is=!1,(mi.length||vi.length)&&ss()}function ss(){is||(is=!0,queueMicrotask(nn))}function on(t){let e;for(;e=t.shift();)try{e()}catch(i){console.error(i)}}function rn(t,e){const i=t.indexOf(e);return~i&&t.splice(i,1)}class an{init(){this.positions=[];let e;this.unbind=y(document,"mousemove",i=>e=kt(i)),this.interval=setInterval(()=>{e&&(this.positions.push(e),this.positions.length>5&&this.positions.shift())},50)}cancel(){var e;(e=this.unbind)==null||e.call(this),clearInterval(this.interval)}movesTo(e){if(!this.positions||this.positions.length<2)return!1;const i=m(e),{left:s,right:n,top:o,bottom:r}=i,[a]=this.positions,l=Ft(this.positions),c=[a,l];return si(l,i)?!1:[[{x:s,y:o},{x:n,y:r}],[{x:s,y:r},{x:n,y:o}]].some(d=>{const f=Ar(c,d);return f&&si(f,i)})}}function Ar([{x:t,y:e},{x:i,y:s}],[{x:n,y:o},{x:r,y:a}]){const l=(a-o)*(i-t)-(r-n)*(s-e);if(l===0)return!1;const c=((r-n)*(e-o)-(a-o)*(t-n))/l;return c<0?!1:{x:t+c*(i-t),y:e+c*(s-e)}}function ln(t,e,i={},{intersecting:s=!0}={}){const n=new IntersectionObserver(s?(o,r)=>{o.some(a=>a.isIntersecting)&&e(o,r)}:e,i);for(const o of T(t))n.observe(o);return n}const Or=Wt&&window.ResizeObserver;function Le(t,e,i={box:"border-box"}){if(Or)return hn(ResizeObserver,t,e,i);const s=[y(window,"load resize",e),y(document,"loadedmetadata load",e,!0)];return{disconnect:()=>s.map(n=>n())}}function ns(t){return{disconnect:y([window,window.visualViewport],"resize",t)}}function os(t,e,i){return hn(MutationObserver,t,e,i)}function hn(t,e,i,s){const n=new t(i);for(const o of T(e))n.observe(o,s);return n}function rs(t){ls(t)&&hs(t,{func:"playVideo",method:"play"}),as(t)&&t.play().catch(A)}function bi(t){ls(t)&&hs(t,{func:"pauseVideo",method:"pause"}),as(t)&&t.pause()}function cn(t){ls(t)&&hs(t,{func:"mute",method:"setVolume",value:0}),as(t)&&(t.muted=!0)}function as(t){return z(t,"video")}function ls(t){return z(t,"iframe")&&(un(t)||dn(t))}function un(t){return!!t.src.match(/\/\/.*?youtube(-nocookie)?\.[a-z]+\/(watch\?v=[^&\s]+|embed)|youtu\.be\/.*/)}function dn(t){return!!t.src.match(/vimeo\.com\/video\/.*/)}async function hs(t,e){await Mr(t),fn(t,e)}function fn(t,e){t.contentWindow.postMessage(JSON.stringify({event:"command",...e}),"*")}const cs="_ukPlayer";let Dr=0;function Mr(t){if(t[cs])return t[cs];const e=un(t),i=dn(t),s=++Dr;let n;return t[cs]=new Promise(o=>{e&&L(t,"load",()=>{const r=()=>fn(t,{event:"listening",id:s});n=setInterval(r,100),r()}),L(window,"message",o,!1,({data:r})=>{try{return r=JSON.parse(r),e&&(r==null?void 0:r.id)===s&&r.event==="onReady"||i&&Number(r==null?void 0:r.player_id)===s}catch{}}),t.src=`${t.src}${b(t.src,"?")?"&":"?"}${e?"enablejsapi=1":`api=1&player_id=${s}`}`}).then(()=>clearInterval(n))}function Br(t,e=0,i=0){return q(t)?ii(...Vt(t).map(s=>{const{top:n,left:o,bottom:r,right:a}=rt(s);return{top:n-e,left:o-i,bottom:r+e,right:a+i}}).concat(E(t))):!1}function pn(t,{offset:e=0}={}){const i=q(t)?Ut(t,!1,["hidden"]):[];return i.reduce((r,a,l)=>{const{scrollTop:c,scrollHeight:u,offsetHeight:d}=a,f=rt(a),g=u-f.height,{height:w,top:I}=i[l-1]?rt(i[l-1]):E(t);let P=Math.ceil(I-f.top-e+c);return e>0&&d<w+e?P+=e:e=0,P>g?(e-=P-g,P=g):P<0&&(e-=P,P=0),()=>s(a,P-c,t,g).then(r)},()=>Promise.resolve())();function s(r,a,l,c){return new Promise(u=>{const d=r.scrollTop,f=n(Math.abs(a)),g=Date.now(),w=fs(r)===r,I=E(l).top+(w?0:d);let P=0,ht=15;(function It(){const Mt=o(K((Date.now()-g)/f));let wt=0;i[0]===r&&d+a<c&&(wt=E(l).top+(w?0:r.scrollTop)-I-m(us(l)).height),h(r,"scrollBehavior")!=="auto"&&h(r,"scrollBehavior","auto"),r.scrollTop=d+(a+wt)*Mt,h(r,"scrollBehavior",""),Mt===1&&(P===wt||!ht--)?u():(P=wt,requestAnimationFrame(It))})()})}function n(r){return 40*Math.pow(r,.375)}function o(r){return .5*(1-Math.cos(Math.PI*r))}}function wi(t,e=0,i=0){if(!q(t))return 0;const s=Ot(t,!0),{scrollHeight:n,scrollTop:o}=s,{height:r}=rt(s),a=n-r,l=Fe(t)[0]-Fe(s)[0],c=Math.max(0,l-r+e),u=Math.min(a,l+t.offsetHeight-i);return c<u?K((o-c)/(u-c)):1}function Ut(t,e=!1,i=[]){const s=fs(t);let n=he(t).reverse();n=n.slice(n.indexOf(s)+1);const o=xt(n,r=>h(r,"position")==="fixed");return~o&&(n=n.slice(o)),[s].concat(n.filter(r=>h(r,"overflow").split(" ").some(a=>b(["auto","scroll",...i],a))&&(!e||r.scrollHeight>rt(r).height))).reverse()}function Ot(...t){return Ut(...t)[0]}function Vt(t){return Ut(t,!1,["hidden","clip"])}function rt(t){const e=zt(t),i=fs(t),s=!Te(t)||t.contains(i);if(s&&e.visualViewport){let{height:l,width:c,scale:u,pageTop:d,pageLeft:f}=e.visualViewport;return l=Math.round(l*u),c=Math.round(c*u),{height:l,width:c,top:d,left:f,bottom:d+l,right:f+c}}let n=E(s?e:t);if(h(t,"display")==="inline")return n;const{body:o,documentElement:r}=e.document,a=s?i===r||i.clientHeight<o.clientHeight?i:o:t;for(let[l,c,u,d]of[["width","x","left","right"],["height","y","top","bottom"]]){const f=n[l]%1;n[u]+=k(h(a,`border-${u}-width`)),n[l]=n[c]=a[`client${Nt(l)}`]-(f?f<.5?-f:1-f:0),n[d]=n[l]+n[u]}return n}function us(t){const{left:e,width:i,top:s}=m(t);for(const n of s?[0,s]:[0]){let o;for(const r of zt(t).document.elementsFromPoint(e+i/2,n))!r.contains(t)&&!x(r,"uk-togglable-leave")&&(ds(r,"fixed")&&gn(he(t).reverse().find(a=>!a.contains(r)&&!ds(a,"static")))<gn(r)||ds(r,"sticky")&&O(r).contains(t))&&(!o||m(o).height<m(r).height)&&(o=r);if(o)return o}}function gn(t){return k(h(t,"zIndex"))}function ds(t,e){return h(t,"position")===e}function fs(t){return zt(t).document.scrollingElement}const at=[["width","x","left","right"],["height","y","top","bottom"]];function mn(t,e,i){i={attach:{element:["left","top"],target:["left","top"],...i.attach},offset:[0,0],placement:[],...i},J(e)||(e=[e,e]),E(t,vn(t,e,i))}function vn(t,e,i){const s=bn(t,e,i),{boundary:n,viewportOffset:o=0,placement:r}=i;let a=s;for(const[l,[c,,u,d]]of Object.entries(at)){const f=Nr(t,e[l],o,n,l);if(xi(s,f,l))continue;let g=0;if(r[l]==="flip"){const w=i.attach.target[l];if(w===d&&s[d]<=f[d]||w===u&&s[u]>=f[u])continue;g=Fr(t,e,i,l)[u]-s[u];const I=zr(t,e[l],o,l);if(!xi(ps(s,g,l),I,l)){if(xi(s,I,l))continue;if(i.recursion)return!1;const P=Hr(t,e,i);if(P&&xi(P,I,1-l))return P;continue}}else if(r[l]==="shift"){const w=E(e[l]),{offset:I}=i;g=K(K(s[u],f[u],f[d]-s[c]),w[u]-s[c]+I[l],w[d]-I[l])-s[u]}a=ps(a,g,l)}return a}function bn(t,e,i){let{attach:s,offset:n}={attach:{element:["left","top"],target:["left","top"],...i.attach},offset:[0,0],...i},o=E(t);for(const[r,[a,,l,c]]of Object.entries(at)){const u=s.target[r]===s.element[r]?rt(e[r]):E(e[r]);o=ps(o,u[l]-o[l]+wn(s.target[r],c,u[a])-wn(s.element[r],c,o[a])+ +n[r],r)}return o}function ps(t,e,i){const[,s,n,o]=at[i],r={...t};return r[n]=t[s]=t[n]+e,r[o]+=e,r}function wn(t,e,i){return t==="center"?i/2:t===e?i:0}function Nr(t,e,i,s,n){let o=$n(...xn(t,e).map(rt));return i&&(o[at[n][2]]+=i,o[at[n][3]]-=i),s&&(o=$n(o,E(J(s)?s[n]:s))),o}function zr(t,e,i,s){const[n,o,r,a]=at[s],[l]=xn(t,e),c=rt(l);return["auto","scroll"].includes(h(l,`overflow-${o}`))&&(c[r]-=l[`scroll${Nt(r)}`],c[a]=c[r]+l[`scroll${Nt(n)}`]),c[r]+=i,c[a]-=i,c}function xn(t,e){return Vt(e).filter(i=>i.contains(t))}function $n(...t){let e={};for(const i of t)for(const[,,s,n]of at)e[s]=Math.max(e[s]||0,i[s]),e[n]=Math.min(...[e[n],i[n]].filter(Boolean));return e}function xi(t,e,i){const[,,s,n]=at[i];return t[s]>=e[s]&&t[n]<=e[n]}function Fr(t,e,{offset:i,attach:s},n){return bn(t,e,{attach:{element:yn(s.element,n),target:yn(s.target,n)},offset:Lr(i,n)})}function Hr(t,e,i){return vn(t,e,{...i,attach:{element:i.attach.element.map(kn).reverse(),target:i.attach.target.map(kn).reverse()},offset:i.offset.reverse(),placement:i.placement.reverse(),recursion:!0})}function yn(t,e){const i=[...t],s=at[e].indexOf(t[e]);return~s&&(i[e]=at[e][1-s%2+2]),i}function kn(t){for(let e=0;e<at.length;e++){const i=at[e].indexOf(t);if(~i)return at[1-e][i%2+2]}}function Lr(t,e){return t=[...t],t[e]*=-1,t}var Wr=Object.freeze({__proto__:null,$,$$:D,Animation:Pt,Dimensions:Ri,MouseTracker:an,Transition:N,addClass:S,after:di,append:W,apply:_t,assign:ft,attr:p,before:ui,boxModelAdjust:de,camelize:ke,children:B,clamp:K,createEvent:ue,css:h,data:Z,dimensions:m,each:oe,empty:Qs,endsWith:ee,escape:Gi,fastdom:At,filter:Oe,find:Vi,findAll:Me,findIndex:xt,flipPosition:gi,fragment:St,getCoveringElement:us,getEventPos:kt,getIndex:ot,getTargetedElement:Ui,hasAttr:Et,hasClass:x,hasOwn:gt,hasTouch:re,height:et,html:bt,hyphenate:Bt,inBrowser:Wt,includes:b,index:yt,intersectRect:ii,isArray:J,isBoolean:ne,isDocument:Ie,isElement:se,isEmpty:ti,isEqual:Ce,isFocusable:li,isFunction:nt,isInView:Br,isInput:ai,isNode:Te,isNumber:Ee,isNumeric:vt,isObject:Tt,isPlainObject:Se,isRtl:U,isSameSiteAnchor:ce,isString:F,isTag:z,isTouch:pt,isUndefined:X,isVisible:q,isVoidElement:qi,isWindow:Qe,last:Ft,matches:C,memoize:ct,mute:cn,noop:A,observeIntersection:ln,observeMutation:os,observeResize:Le,observeViewportResize:ns,off:Rt,offset:E,offsetPosition:Fe,offsetViewport:rt,on:y,once:L,overflowParents:Vt,parent:O,parents:he,pause:bi,pick:ei,play:rs,pointInRect:si,pointerCancel:ri,pointerDown:ut,pointerEnter:jt,pointerLeave:le,pointerMove:oi,pointerUp:Ct,position:es,positionAt:mn,prepend:xr,propName:hi,query:tt,queryAll:De,ready:wr,remove:Q,removeAttr:Pe,removeClass:_,replaceClass:ni,scrollIntoView:pn,scrollParent:Ot,scrollParents:Ut,scrolledOver:wi,selFocusable:Ae,selInput:_e,sortBy:Rs,startsWith:mt,sumBy:Ht,swap:Wi,toArray:ie,toBoolean:Li,toEventTargets:Ji,toFloat:k,toNode:R,toNodes:T,toNumber:$t,toPx:G,toWindow:zt,toggleClass:H,trigger:v,ucfirst:Nt,uniqueBy:qs,unwrap:ze,width:pi,wrapAll:Ne,wrapInner:ts}),it={connected(){S(this.$el,this.$options.id)}};const jr=["days","hours","minutes","seconds"];var Rr={mixins:[it],props:{date:String,clsWrapper:String,role:String,reload:Boolean},data:{date:"",clsWrapper:".uk-countdown-%unit%",role:"timer",reload:!1},connected(){p(this.$el,"role",this.role),this.date=k(Date.parse(this.$props.date)),this.started=this.end=!1,this.start()},disconnected(){this.stop()},events:{name:"visibilitychange",el:()=>document,handler(){document.hidden?this.stop():this.start()}},methods:{start(){this.stop(),this.update()},stop(){this.timer&&(clearInterval(this.timer),v(this.$el,"countdownstop"),this.timer=null)},update(){const t=qr(this.date);t.total?this.timer||(this.started=!0,v(this.$el,"countdownstart"),this.timer=setInterval(this.update,1e3)):(this.stop(),this.end||(v(this.$el,"countdownend"),this.end=!0,this.reload&&this.started&&window.location.reload()));for(const e of jr){const i=$(this.clsWrapper.replace("%unit%",e),this.$el);if(!i)continue;let s=Math.trunc(t[e]).toString().padStart(2,"0");i.textContent!==s&&(s=s.split(""),s.length!==i.children.length&&bt(i,s.map(()=>"<span></span>").join("")),s.forEach((n,o)=>i.children[o].textContent=n))}}}};function qr(t){const e=Math.max(0,t-Date.now())/1e3;return{total:e,seconds:e%60,minutes:e/60%60,hours:e/60/60%24,days:e/60/60/24}}const V={};V.events=V.watch=V.observe=V.created=V.beforeConnect=V.connected=V.beforeDisconnect=V.disconnected=V.destroy=gs,V.args=function(t,e){return e!==!1&&gs(e||t)},V.update=function(t,e){return Rs(gs(t,nt(e)?{read:e}:e),"order")},V.props=function(t,e){if(J(e)){const i={};for(const s of e)i[s]=String;e=i}return V.methods(t,e)},V.computed=V.methods=function(t,e){return e?t?{...t,...e}:e:t},V.i18n=V.data=function(t,e,i){return i?Sn(t,e,i):e?t?function(s){return Sn(t,e,s)}:e:t};function Sn(t,e,i){return V.computed(nt(t)?t.call(i,i):t,nt(e)?e.call(i,i):e)}function gs(t,e){return t=t&&!J(t)?[t]:t,e?t?t.concat(e):J(e)?e:[e]:t}function Ur(t,e){return X(e)?t:e}function We(t,e,i){const s={};if(nt(e)&&(e=e.options),e.extends&&(t=We(t,e.extends,i)),e.mixins)for(const o of e.mixins)t=We(t,o,i);for(const o in t)n(o);for(const o in e)gt(t,o)||n(o);function n(o){s[o]=(V[o]||Ur)(t[o],e[o],i)}return s}function pe(t,e=[]){try{return t?mt(t,"{")?JSON.parse(t):e.length&&!b(t,":")?{[e[0]]:t}:t.split(";").reduce((i,s)=>{const[n,o]=s.split(/:(.*)/);return n&&!X(o)&&(i[n.trim()]=o.trim()),i},{}):{}}catch{return{}}}function ms(t,e){return t===Boolean?Li(e):t===Number?$t(e):t==="list"?Yr(e):t===Object&&F(e)?pe(e):t?t(e):e}const Vr=/,(?![^(]*\))/;function Yr(t){return J(t)?t:F(t)?t.split(Vr).map(e=>vt(e)?$t(e):Li(e.trim())):[t]}function Gr(t){t._data={},t._updates=[...t.$options.update||[]],t._disconnect.push(()=>t._updates=t._data=null)}function Xr(t,e){t._updates.unshift(e)}function je(t,e="update"){t._connected&&t._updates.length&&(t._queued||(t._queued=new Set,At.read(()=>{t._connected&&Jr(t,t._queued),t._queued=null})),t._queued.add(e.type||e))}function Jr(t,e){for(const{read:i,write:s,events:n=[]}of t._updates){if(!e.has("update")&&!n.some(r=>e.has(r)))continue;let o;i&&(o=i.call(t,t._data,e),o&&Se(o)&&ft(t._data,o)),s&&o!==!1&&At.write(()=>{t._connected&&s.call(t,t._data,e)})}}function dt(t){return qe(Le,t,"resize")}function ge(t){return qe(ln,t)}function $i(t){return qe(os,t)}function yi(t={}){return ge({handler:function(e,i){const{targets:s=this.$el,preload:n=5}=t;for(const o of T(nt(s)?s(this):s))D('[loading="lazy"]',o).slice(0,n-1).forEach(r=>Pe(r,"loading"));for(const o of e.filter(({isIntersecting:r})=>r).map(({target:r})=>r))i.unobserve(o)},...t})}function vs(t){return qe((e,i)=>ns(i),t,"resize")}function Re(t){return qe((e,i)=>({disconnect:y(Zr(e),"scroll",i,{passive:!0})}),t,"scroll")}function In(t){return{observe(e,i){return{observe:A,unobserve:A,disconnect:y(e,ut,i,{passive:!0})}},handler(e){if(!pt(e))return;const i=kt(e),s="tagName"in e.target?e.target:O(e.target);L(document,`${Ct} ${ri} scroll`,n=>{const{x:o,y:r}=kt(n);(n.type!=="scroll"&&s&&o&&Math.abs(i.x-o)>100||r&&Math.abs(i.y-r)>100)&&setTimeout(()=>{v(s,"swipe"),v(s,`swipe${Kr(i.x,i.y,o,r)}`)})})},...t}}function qe(t,e,i){return{observe:t,handler(){je(this,i)},...e}}function Kr(t,e,i,s){return Math.abs(t-i)>=Math.abs(e-s)?t-i>0?"Left":"Right":e-s>0?"Up":"Down"}function Zr(t){return T(t).map(e=>{const{ownerDocument:i}=e,s=Ot(e,!0);return s===i.scrollingElement?i:s})}var Tn={props:{margin:String,firstColumn:Boolean},data:{margin:"uk-margin-small-top",firstColumn:"uk-first-column"},observe:[$i({options:{childList:!0}}),$i({options:{attributes:!0,attributeFilter:["style"]},target:({$el:t})=>[t,...B(t)]}),dt({target:({$el:t})=>[t,...B(t)]})],update:{read(){return{rows:bs(B(this.$el))}},write({rows:t}){for(const e of t)for(const i of e)H(i,this.margin,t[0]!==e),H(i,this.firstColumn,e[U?e.length-1:0]===i)},events:["resize"]}};function bs(t){const e=[[]],i=t.some((s,n)=>n&&t[n-1].offsetParent!==s.offsetParent);for(const s of t){if(!q(s))continue;const n=ws(s,i);for(let o=e.length-1;o>=0;o--){const r=e[o];if(!r[0]){r.push(s);break}const a=ws(r[0],i);if(n.top>=a.bottom-1&&n.top!==a.top){e.push([s]);break}if(n.bottom-1>a.top||n.top===a.top){let l=r.length-1;for(;l>=0;l--){const c=ws(r[l],i);if(n.left>=c.left)break}r.splice(l+1,0,s);break}if(o===0){e.unshift([s]);break}}}return e}function ws(t,e=!1){let{offsetTop:i,offsetLeft:s,offsetHeight:n,offsetWidth:o}=t;return e&&([i,s]=Fe(t)),{top:i,left:s,bottom:i+n,right:s+o}}async function Qr(t,e,i){await xs();let s=B(e);const n=s.map(g=>En(g,!0)),o={...h(e,["height","padding"]),display:"block"},r=s.concat(e);await Promise.all(r.map(N.cancel)),h(r,"transitionProperty","none"),await t(),s=s.concat(B(e).filter(g=>!b(s,g))),await Promise.resolve(),h(r,"transitionProperty","");const a=p(e,"style"),l=h(e,["height","padding"]),[c,u]=ta(e,s,n),d=s.map(g=>({style:p(g,"style")}));s.forEach((g,w)=>u[w]&&h(g,u[w])),h(e,o),v(e,"scroll"),await xs();const f=s.map((g,w)=>O(g)===e&&N.start(g,c[w],i,"ease")).concat(N.start(e,l,i,"ease"));try{await Promise.all(f),s.forEach((g,w)=>{p(g,d[w]),O(g)===e&&h(g,"display",c[w].opacity===0?"none":"")}),p(e,"style",a)}catch{p(s,"style",""),ea(e,o)}}function En(t,e){const i=h(t,"zIndex");return q(t)?{display:"",opacity:e?h(t,"opacity"):"0",pointerEvents:"none",position:"absolute",zIndex:i==="auto"?yt(t):i,...Cn(t)}:!1}function ta(t,e,i){const s=e.map((o,r)=>O(o)&&r in i?i[r]?q(o)?Cn(o):{opacity:0}:{opacity:q(o)?1:0}:!1),n=s.map((o,r)=>{const a=O(e[r])===t&&(i[r]||En(e[r]));if(!a)return!1;if(!o)delete a.opacity;else if(!("opacity"in o)){const{opacity:l}=a;l%1?o.opacity=1:delete a.opacity}return a});return[s,n]}function ea(t,e){for(const i in e)h(t,i,"")}function Cn(t){const{height:e,width:i}=m(t);return{height:e,width:i,transform:"",...es(t),...h(t,["marginTop","marginLeft"])}}function xs(){return new Promise(t=>requestAnimationFrame(t))}const $s="uk-transition-leave",ys="uk-transition-enter";function Pn(t,e,i,s=0){const n=ki(e,!0),o={opacity:1},r={opacity:0},a=u=>()=>n===ki(e)?u():Promise.reject(),l=a(async()=>{S(e,$s),await Promise.all(An(e).map((u,d)=>new Promise(f=>setTimeout(()=>N.start(u,r,i/2,"ease").then(f),d*s)))),_(e,$s)}),c=a(async()=>{const u=et(e);S(e,ys),t(),h(B(e),{opacity:0}),await xs();const d=B(e),f=et(e);h(e,"alignContent","flex-start"),et(e,u);const g=An(e);h(d,r);const w=g.map(async(I,P)=>{await ia(P*s),await N.start(I,o,i/2,"ease")});u!==f&&w.push(N.start(e,{height:f},i/2+g.length*s,"ease")),await Promise.all(w).then(()=>{_(e,ys),n===ki(e)&&(h(e,{height:"",alignContent:""}),h(d,{opacity:""}),delete e.dataset.transition)})});return x(e,$s)?_n(e).then(c):x(e,ys)?_n(e).then(l).then(c):l().then(c)}function ki(t,e){return e&&(t.dataset.transition=1+ki(t)),$t(t.dataset.transition)||0}function _n(t){return Promise.all(B(t).filter(N.inProgress).map(e=>new Promise(i=>L(e,"transitionend transitioncanceled",i))))}function An(t){return bs(B(t)).flat().filter(q)}function ia(t){return new Promise(e=>setTimeout(e,t))}var On={props:{duration:Number,animation:Boolean},data:{duration:150,animation:"slide"},methods:{animate(t,e=this.$el){const i=this.animation;return(i==="fade"?Pn:i==="delayed-fade"?(...n)=>Pn(...n,40):i?Qr:()=>(t(),Promise.resolve()))(t,e,this.duration).catch(A)}}};const M={TAB:9,ESC:27,SPACE:32,END:35,HOME:36,LEFT:37,UP:38,RIGHT:39,DOWN:40};var sa={mixins:[On],args:"target",props:{target:String,selActive:Boolean},data:{target:"",selActive:!1,attrItem:"uk-filter-control",cls:"uk-active",duration:250},computed:{children:({target:t},e)=>D(`${t} > *`,e),toggles:({attrItem:t},e)=>D(`[${t}],[data-${t}]`,e)},watch:{toggles(t){this.updateState();const e=D(this.selActive,this.$el);for(const i of t){this.selActive!==!1&&H(i,this.cls,b(e,i));const s=la(i);z(s,"a")&&p(s,"role","button")}},children(t,e){e&&this.updateState()}},events:{name:"click keydown",delegate:({attrItem:t})=>`[${t}],[data-${t}]`,handler(t){t.type==="keydown"&&t.keyCode!==M.SPACE||t.target.closest("a,button")&&(t.preventDefault(),this.apply(t.current))}},methods:{apply(t){const e=this.getState(),i=Mn(t,this.attrItem,this.getState());na(e,i)||this.setState(i)},getState(){return this.toggles.filter(t=>x(t,this.cls)).reduce((t,e)=>Mn(e,this.attrItem,t),{filter:{"":""},sort:[]})},async setState(t,e=!0){t={filter:{"":""},sort:[],...t},v(this.$el,"beforeFilter",[this,t]);for(const i of this.toggles)H(i,this.cls,ra(i,this.attrItem,t));await Promise.all(D(this.target,this.$el).map(i=>{const s=()=>oa(t,i,B(i));return e?this.animate(s,i):s()})),v(this.$el,"afterFilter",[this])},updateState(){At.write(()=>this.setState(this.getState(),!1))}}};function Dn(t,e){return pe(Z(t,e),["filter"])}function na(t,e){return["filter","sort"].every(i=>Ce(t[i],e[i]))}function oa(t,e,i){for(const o of i)h(o,"display",Object.values(t.filter).every(r=>!r||C(o,r))?"":"none");const[s,n]=t.sort;if(s){const o=aa(i,s,n);Ce(o,i)||W(e,o)}}function Mn(t,e,i){const{filter:s,group:n,sort:o,order:r="asc"}=Dn(t,e);return(s||X(o))&&(n?s?(delete i.filter[""],i.filter[n]=s):(delete i.filter[n],(ti(i.filter)||""in i.filter)&&(i.filter={"":s||""})):i.filter={"":s||""}),X(o)||(i.sort=[o,r]),i}function ra(t,e,{filter:i={"":""},sort:[s,n]}){const{filter:o="",group:r="",sort:a,order:l="asc"}=Dn(t,e);return X(a)?r in i&&o===i[r]||!o&&r&&!(r in i)&&!i[""]:s===a&&n===l}function aa(t,e,i){return[...t].sort((s,n)=>Z(s,e).localeCompare(Z(n,e),void 0,{numeric:!0})*(i==="asc"||-1))}function la(t){return $("a,button",t)||t}var ha={args:"dataSrc",props:{dataSrc:String,sources:String,margin:String,target:String,loading:String},data:{dataSrc:"",sources:!1,margin:"50%",target:!1,loading:"lazy"},connected(){this.loading!=="lazy"?this.load():Ss(this.$el)&&(this.$el.loading="lazy",ks(this.$el))},disconnected(){this.img&&(this.img.onload=""),delete this.img},observe:ge({handler(t,e){this.load(),e.disconnect()},options:({margin:t})=>({rootMargin:t}),filter:({loading:t})=>t==="lazy",target:({$el:t,$props:e})=>e.target?[t,...De(e.target,t)]:t}),methods:{load(){if(this.img)return this.img;const t=Ss(this.$el)?this.$el:ua(this.$el,this.dataSrc,this.sources);return Pe(t,"loading"),ks(this.$el,t.currentSrc),this.img=t}}};function ks(t,e){if(Ss(t)){const i=O(t);(z(i,"picture")?B(i):[t]).forEach(n=>Bn(n,n))}else e&&!b(t.style.backgroundImage,e)&&(h(t,"backgroundImage",`url(${Gi(e)})`),v(t,ue("load",!1)))}const ca=["data-src","data-srcset","sizes"];function Bn(t,e){for(const i of ca){const s=Z(t,i);s&&p(e,i.replace(/data-/g,""),s)}}function ua(t,e,i){const s=new Image;return Nn(s,i),Bn(t,s),s.onload=()=>ks(t,s.currentSrc),p(s,"src",e),s}function Nn(t,e){if(e=da(e),e.length){const i=St("<picture>");for(const s of e){const n=St("<source>");p(n,s),W(i,n)}W(i,t)}}function da(t){if(!t)return[];if(mt(t,"["))try{t=JSON.parse(t)}catch{t=[]}else t=pe(t);return J(t)||(t=[t]),t.filter(e=>!ti(e))}function Ss(t){return z(t,"img")}let Is;function zn(t){const e=y(t,"touchstart",s=>{if(s.targetTouches.length!==1||C(s.target,'input[type="range"'))return;let n=kt(s).y;const o=y(t,"touchmove",r=>{const a=kt(r).y;a!==n&&(n=a,Ut(r.target).some(l=>{if(!t.contains(l))return!1;let{scrollHeight:c,clientHeight:u}=l;return u<c})||r.preventDefault())},{passive:!1});L(t,"scroll touchend touchcanel",o,{capture:!0})},{passive:!0});if(Is)return e;Is=!0;const{scrollingElement:i}=document;return h(i,{overflowY:CSS.supports("overflow","clip")?"clip":"hidden",touchAction:"none",paddingRight:pi(window)-i.clientWidth||""}),()=>{Is=!1,e(),h(i,{overflowY:"",touchAction:"",paddingRight:""})}}var Ue={props:{container:Boolean},data:{container:!0},computed:{container({container:t}){return t===!0&&this.$container||t&&$(t)}}},Fn={props:{pos:String,offset:Boolean,flip:Boolean,shift:Boolean,inset:Boolean},data:{pos:`bottom-${U?"right":"left"}`,offset:!1,flip:!0,shift:!0,inset:!1},connected(){this.pos=this.$props.pos.split("-").concat("center").slice(0,2),[this.dir,this.align]=this.pos,this.axis=b(["top","bottom"],this.dir)?"y":"x"},methods:{positionAt(t,e,i){let s=[this.getPositionOffset(t),this.getShiftOffset(t)];const n=[this.flip&&"flip",this.shift&&"shift"],o={element:[this.inset?this.dir:gi(this.dir),this.align],target:[this.dir,this.align]};if(this.axis==="y"){for(const l in o)o[l].reverse();s.reverse(),n.reverse()}const r=Ts(t),a=m(t);h(t,{top:-a.height,left:-a.width}),mn(t,e,{attach:o,offset:s,boundary:i,placement:n,viewportOffset:this.getViewportOffset(t)}),r()},getPositionOffset(t=this.$el){return G(this.offset===!1?h(t,"--uk-position-offset"):this.offset,this.axis==="x"?"width":"height",t)*(b(["left","top"],this.dir)?-1:1)*(this.inset?-1:1)},getShiftOffset(t=this.$el){return this.align==="center"?0:G(h(t,"--uk-position-shift-offset"),this.axis==="y"?"width":"height",t)*(b(["left","top"],this.align)?1:-1)},getViewportOffset(t){return G(h(t,"--uk-position-viewport-offset"))}}};function Ts(t){const e=Ot(t),{scrollTop:i}=e;return()=>{i!==e.scrollTop&&(e.scrollTop=i)}}var Yt={props:{cls:Boolean,animation:"list",duration:Number,velocity:Number,origin:String,transition:String},data:{cls:!1,animation:[!1],duration:200,velocity:.2,origin:!1,transition:"ease",clsEnter:"uk-togglable-enter",clsLeave:"uk-togglable-leave"},computed:{hasAnimation:({animation:t})=>!!t[0],hasTransition:({animation:t})=>["slide","reveal"].some(e=>mt(t[0],e))},methods:{async toggleElement(t,e,i){try{return await Promise.all(T(t).map(s=>{const n=ne(e)?e:!this.isToggled(s);if(!v(s,`before${n?"show":"hide"}`,[this]))return Promise.reject();const o=(nt(i)?i:i===!1||!this.hasAnimation?fa:this.hasTransition?pa:ga)(s,n,this),r=n?this.clsEnter:this.clsLeave;S(s,r),v(s,n?"show":"hide",[this]);const a=()=>{var l;if(_(s,r),v(s,n?"shown":"hidden",[this]),n){const c=Ts(s);(l=D("[autofocus]",s).find(q))==null||l.focus(),c()}};return o?o.then(a,()=>(_(s,r),Promise.reject())):a()})),!0}catch{return!1}},isToggled(t=this.$el){return t=R(t),x(t,this.clsEnter)?!0:x(t,this.clsLeave)?!1:this.cls?x(t,this.cls.split(" ")[0]):q(t)},_toggle(t,e){if(!t)return;e=!!e;let i;this.cls?(i=b(this.cls," ")||e!==x(t,this.cls),i&&H(t,this.cls,b(this.cls," ")?void 0:e)):(i=e===t.hidden,i&&(t.hidden=!e)),i&&v(t,"toggled",[e,this])}}};function fa(t,e,{_toggle:i}){return Pt.cancel(t),N.cancel(t),i(t,e)}async function pa(t,e,{animation:i,duration:s,velocity:n,transition:o,_toggle:r}){var a;const[l="reveal",c="top"]=((a=i[0])==null?void 0:a.split("-"))||[],u=[["left","right"],["top","bottom"]],d=u[b(u[0],c)?0:1],f=d[1]===c,w=["width","height"][u.indexOf(d)],I=`margin-${d[0]}`,P=`margin-${c}`;let ht=m(t)[w];const It=N.inProgress(t);await N.cancel(t),e&&r(t,!0);const Mt=Object.fromEntries(["padding","border","width","height","minWidth","minHeight","overflowY","overflowX",I,P].map(sr=>[sr,t.style[sr]])),wt=m(t),js=k(h(t,I)),tr=k(h(t,P)),te=wt[w]+tr;!It&&!e&&(ht+=tr);const[Fi]=ts(t,"<div>");h(Fi,{boxSizing:"border-box",height:wt.height,width:wt.width,...h(t,["overflow","padding","borderTop","borderRight","borderBottom","borderLeft","borderImage",P])}),h(t,{padding:0,border:0,minWidth:0,minHeight:0,[P]:0,width:wt.width,height:wt.height,overflow:"hidden",[w]:ht});const er=ht/te;s=(n*te+s)*(e?1-er:er);const ir={[w]:e?te:0};f&&(h(t,I,te-ht+js),ir[I]=e?js:te+js),!f^l==="reveal"&&(h(Fi,I,-te+ht),N.start(Fi,{[I]:e?0:-te},s,o));try{await N.start(t,ir,s,o)}finally{h(t,Mt),ze(Fi.firstChild),e||r(t,!1)}}function ga(t,e,i){const{animation:s,duration:n,_toggle:o}=i;return e?(o(t,!0),Pt.in(t,s[0],n,i.origin)):Pt.out(t,s[1]||s[0],n,i.origin).then(()=>o(t,!1))}const st=[];var Es={mixins:[it,Ue,Yt],props:{selPanel:String,selClose:String,escClose:Boolean,bgClose:Boolean,stack:Boolean,role:String},data:{cls:"uk-open",escClose:!0,bgClose:!0,overlay:!0,stack:!1,role:"dialog"},computed:{panel:({selPanel:t},e)=>$(t,e),transitionElement(){return this.panel}},connected(){p(this.panel||this.$el,"role",this.role),this.overlay&&p(this.panel||this.$el,"aria-modal",!0)},beforeDisconnect(){b(st,this)&&this.toggleElement(this.$el,!1,!1)},events:[{name:"click",delegate:({selClose:t})=>`${t},a[href*="#"]`,handler(t){const{current:e,defaultPrevented:i}=t,{hash:s}=e;!i&&s&&ce(e)&&!this.$el.contains($(s))?this.hide():C(e,this.selClose)&&(t.preventDefault(),this.hide())}},{name:"toggle",self:!0,handler(t){t.defaultPrevented||(t.preventDefault(),this.isToggled()===b(st,this)&&this.toggle())}},{name:"beforeshow",self:!0,handler(t){if(b(st,this))return!1;!this.stack&&st.length?(Promise.all(st.map(e=>e.hide())).then(this.show),t.preventDefault()):st.push(this)}},{name:"show",self:!0,handler(){this.stack&&h(this.$el,"zIndex",k(h(this.$el,"zIndex"))+st.length);const t=[this.overlay&&va(this),this.overlay&&zn(this.$el),this.bgClose&&ba(this),this.escClose&&wa(this)];L(this.$el,"hidden",()=>t.forEach(e=>e&&e()),{self:!0}),S(document.documentElement,this.clsPage)}},{name:"shown",self:!0,handler(){li(this.$el)||p(this.$el,"tabindex","-1"),C(this.$el,":focus-within")||this.$el.focus()}},{name:"hidden",self:!0,handler(){b(st,this)&&st.splice(st.indexOf(this),1),h(this.$el,"zIndex",""),st.some(t=>t.clsPage===this.clsPage)||_(document.documentElement,this.clsPage)}}],methods:{toggle(){return this.isToggled()?this.hide():this.show()},show(){return this.container&&O(this.$el)!==this.container?(W(this.container,this.$el),new Promise(t=>requestAnimationFrame(()=>this.show().then(t)))):this.toggleElement(this.$el,!0,Hn)},hide(){return this.toggleElement(this.$el,!1,Hn)}}};function Hn(t,e,{transitionElement:i,_toggle:s}){return new Promise((n,o)=>L(t,"show hide",()=>{var r;(r=t._reject)==null||r.call(t),t._reject=o,s(t,e);const a=L(i,"transitionstart",()=>{L(i,"transitionend transitioncancel",n,{self:!0}),clearTimeout(l)},{self:!0}),l=setTimeout(()=>{a(),n()},ma(h(i,"transitionDuration")))})).then(()=>delete t._reject)}function ma(t){return t?ee(t,"ms")?k(t):k(t)*1e3:0}function va(t){return y(document,"focusin",e=>{Ft(st)===t&&!t.$el.contains(e.target)&&t.$el.focus()})}function ba(t){return y(document,ut,({target:e})=>{Ft(st)!==t||t.overlay&&!t.$el.contains(e)||!t.panel||t.panel.contains(e)||L(document,`${Ct} ${ri} scroll`,({defaultPrevented:i,type:s,target:n})=>{!i&&s===Ct&&e===n&&t.hide()},!0)})}function wa(t){return y(document,"keydown",e=>{e.keyCode===27&&Ft(st)===t&&t.hide()})}var Cs={slide:{show(t){return[{transform:j(t*-100)},{transform:j()}]},percent(t){return Ve(t)},translate(t,e){return[{transform:j(e*-100*t)},{transform:j(e*100*(1-t))}]}}};function Ve(t){return Math.abs(new DOMMatrix(h(t,"transform")).m41/t.offsetWidth)}function j(t=0,e="%"){return t?`translate3d(${t+e}, 0, 0)`:""}function xa(t,e,i,{animation:s,easing:n}){const{percent:o,translate:r,show:a=A}=s,l=a(i),{promise:c,resolve:u}=Ln();return{dir:i,show(d,f=0,g){const w=g?"linear":n;return d-=Math.round(d*K(f,-1,1)),this.translate(f),Gt(e,"itemin",{percent:f,duration:d,timing:w,dir:i}),Gt(t,"itemout",{percent:1-f,duration:d,timing:w,dir:i}),Promise.all([N.start(e,l[1],d,w),N.start(t,l[0],d,w)]).then(()=>{this.reset(),u()},A),c},cancel(){return N.cancel([e,t])},reset(){for(const d in l[0])h([e,t],d,"")},async forward(d,f=this.percent()){return await this.cancel(),this.show(d,f,!0)},translate(d){this.reset();const f=r(d,i);h(e,f[1]),h(t,f[0]),Gt(e,"itemtranslatein",{percent:d,dir:i}),Gt(t,"itemtranslateout",{percent:1-d,dir:i})},percent(){return o(t||e,e,i)},getDistance(){return t==null?void 0:t.offsetWidth}}}function Gt(t,e,i){v(t,ue(e,!1,!1,i))}function Ln(){let t;return{promise:new Promise(e=>t=e),resolve:t}}var Si={props:{i18n:Object},data:{i18n:null},methods:{t(t,...e){var i,s,n;let o=0;return((n=((i=this.i18n)==null?void 0:i[t])||((s=this.$options.i18n)==null?void 0:s[t]))==null?void 0:n.replace(/%s/g,()=>e[o++]||""))||""}}},$a={props:{autoplay:Boolean,autoplayInterval:Number,pauseOnHover:Boolean},data:{autoplay:!1,autoplayInterval:7e3,pauseOnHover:!0},connected(){p(this.list,"aria-live",this.autoplay?"off":"polite"),this.autoplay&&this.startAutoplay()},disconnected(){this.stopAutoplay()},update(){p(this.slides,"tabindex","-1")},events:[{name:"visibilitychange",el:()=>document,filter:({autoplay:t})=>t,handler(){document.hidden?this.stopAutoplay():this.startAutoplay()}}],methods:{startAutoplay(){this.stopAutoplay(),this.interval=setInterval(()=>{this.stack.length||this.draggable&&C(this.$el,":focus-within")&&!C(this.$el,":focus")||this.pauseOnHover&&C(this.$el,":hover")||this.show("next")},this.autoplayInterval)},stopAutoplay(){clearInterval(this.interval)}}};const Ii={passive:!1,capture:!0},Wn={passive:!0,capture:!0},ya="touchstart mousedown",Ps="touchmove mousemove",jn="touchend touchcancel mouseup click input scroll";var ka={props:{draggable:Boolean},data:{draggable:!0,threshold:10},created(){for(const t of["start","move","end"]){const e=this[t];this[t]=i=>{const s=kt(i).x*(U?-1:1);this.prevPos=s===this.pos?this.prevPos:this.pos,this.pos=s,e(i)}}},events:[{name:ya,passive:!0,delegate:({selList:t})=>`${t} > *`,handler(t){!this.draggable||this.parallax||!pt(t)&&Sa(t.target)||t.target.closest(_e)||t.button>0||this.length<2||this.start(t)}},{name:"dragstart",handler(t){t.preventDefault()}},{name:Ps,el:({list:t})=>t,handler:A,...Ii}],methods:{start(){this.drag=this.pos,this._transitioner?(this.percent=this._transitioner.percent(),this.drag+=this._transitioner.getDistance()*this.percent*this.dir,this._transitioner.cancel(),this._transitioner.translate(this.percent),this.dragging=!0,this.stack=[]):this.prevIndex=this.index,y(document,Ps,this.move,Ii),y(document,jn,this.end,Wn),h(this.list,"userSelect","none")},move(t){const e=this.pos-this.drag;if(e===0||this.prevPos===this.pos||!this.dragging&&Math.abs(e)<this.threshold)return;t.cancelable&&t.preventDefault(),this.dragging=!0,this.dir=e<0?1:-1;let{slides:i,prevIndex:s}=this,n=Math.abs(e),o=this.getIndex(s+this.dir),r=Rn.call(this,s,o);for(;o!==s&&n>r;)this.drag-=r*this.dir,s=o,n-=r,o=this.getIndex(s+this.dir),r=Rn.call(this,s,o);this.percent=n/r;const a=i[s],l=i[o],c=this.index!==o,u=s===o;let d;for(const f of[this.index,this.prevIndex])b([o,s],f)||(v(i[f],"itemhidden",[this]),u&&(d=!0,this.prevIndex=s));(this.index===s&&this.prevIndex!==s||d)&&v(i[this.index],"itemshown",[this]),c&&(this.prevIndex=s,this.index=o,u||(v(a,"beforeitemhide",[this]),v(a,"itemhide",[this])),v(l,"beforeitemshow",[this]),v(l,"itemshow",[this])),this._transitioner=this._translate(Math.abs(this.percent),a,!u&&l)},end(){if(Rt(document,Ps,this.move,Ii),Rt(document,jn,this.end,Wn),this.dragging)if(setTimeout(y(this.list,"click",t=>t.preventDefault(),Ii)),this.dragging=null,this.index===this.prevIndex)this.percent=1-this.percent,this.dir*=-1,this._show(!1,this.index,!0),this._transitioner=null;else{const t=(U?this.dir*(U?1:-1):this.dir)<0==this.prevPos>this.pos;this.index=t?this.index:this.prevIndex,t&&(v(this.slides[this.prevIndex],"itemhidden",[this]),v(this.slides[this.index],"itemshown",[this]),this.percent=1-this.percent),this.show(this.dir>0&&!t||this.dir<0&&t?"next":"previous",!0)}h(this.list,{userSelect:""}),this.drag=this.percent=null}}};function Rn(t,e){return this._getTransitioner(t,t!==e&&e).getDistance()||this.slides[t].offsetWidth}function Sa(t){return h(t,"userSelect")!=="none"&&ie(t.childNodes).some(e=>e.nodeType===3&&e.textContent.trim())}function Ia(t){t._watches=[];for(const e of t.$options.watch||[])for(const[i,s]of Object.entries(e))qn(t,s,i);t._initial=!0}function qn(t,e,i){t._watches.push({name:i,...Se(e)?e:{handler:e}})}function Ta(t,e){for(const{name:i,handler:s,immediate:n=!0}of t._watches)(t._initial&&n||gt(e,i)&&!Ce(e[i],t[i]))&&s.call(t,t[i],e[i]);t._initial=!1}function Ea(t){const{computed:e}=t.$options;if(t._computed={},e)for(const i in e)Vn(t,i,e[i])}const Un={subtree:!0,childList:!0};function Vn(t,e,i){t._hasComputed=!0,Object.defineProperty(t,e,{enumerable:!0,get(){const{_computed:s,$props:n,$el:o}=t;if(!gt(s,e)&&(s[e]=(i.get||i).call(t,n,o),i.observe&&t._computedObserver)){const r=i.observe.call(t,n);t._computedObserver.observe(["~","+","-"].includes(r[0])?o.parentElement:o.getRootNode(),Un)}return s[e]},set(s){const{_computed:n}=t;n[e]=i.set?i.set.call(t,s):s,X(n[e])&&delete n[e]}})}function Ca(t){t._hasComputed&&(Xr(t,{read:()=>Ta(t,Yn(t)),events:["resize","computed"]}),t._computedObserver=os(t.$el,()=>je(t,"computed"),Un),t._disconnect.push(()=>{t._computedObserver.disconnect(),t._computedObserver=null,Yn(t)}))}function Yn(t){const e={...t._computed};return t._computed={},e}function Pa(t){for(const e of t.$options.events||[])if(gt(e,"handler"))Gn(t,e);else for(const i in e)Gn(t,{name:i,handler:e[i]})}function Gn(t,{name:e,el:i,handler:s,capture:n,passive:o,delegate:r,filter:a,self:l}){a&&!a.call(t,t)||t._disconnect.push(y(i?i.call(t,t):t.$el,e,r==null?void 0:r.call(t,t),s.bind(t),{passive:o,capture:n,self:l}))}function _a(t){for(const e of t.$options.observe||[])Aa(t,e)}function Aa(t,e){let{observe:i,target:s=t.$el,handler:n,options:o,filter:r,args:a}=e;if(r&&!r.call(t,t))return;const l=`_observe${t._disconnect.length}`;nt(s)&&!gt(t,l)&&Vn(t,l,()=>{const d=s.call(t,t);return J(d)?T(d):d}),n=F(n)?t[n]:n.bind(t),nt(o)&&(o=o.call(t,t));const c=gt(t,l)?t[l]:s,u=i(c,n,o,a);nt(s)&&J(t[l])&&qn(t,{handler:Oa(u,o),immediate:!1},l),t._disconnect.push(()=>u.disconnect())}function Oa(t,e){return(i,s)=>{for(const n of s)b(i,n)||(t.unobserve?t.unobserve(n):t.observe&&t.disconnect());for(const n of i)(!b(s,n)||!t.unobserve)&&t.observe(n,e)}}function Da(t){const{$options:e,$props:i}=t,s=Xn(e);ft(i,s);const{computed:n,methods:o}=e;for(let r in i)r in s&&(!n||!gt(n,r))&&(!o||!gt(o,r))&&(t[r]=i[r])}function Xn(t){const e={},{args:i=[],props:s={},el:n,id:o}=t;if(!s)return e;for(const a in s){const l=Bt(a);let c=Z(n,l);X(c)||(c=s[a]===Boolean&&c===""?!0:ms(s[a],c),!(l==="target"&&mt(c,"_"))&&(e[a]=c))}const r=pe(Z(n,o),i);for(const a in r){const l=ke(a);X(s[l])||(e[l]=ms(s[l],r[a]))}return e}const Ma=ct((t,e)=>{const i=Object.keys(e),s=i.concat(t).map(n=>[Bt(n),`data-${Bt(n)}`]).flat();return{attributes:i,filter:s}});function Ba(t){const{$options:e,$props:i}=t,{id:s,props:n,el:o}=e;if(!n)return;const{attributes:r,filter:a}=Ma(s,n),l=new MutationObserver(c=>{const u=Xn(e);c.some(({attributeName:d})=>{const f=d.replace("data-","");return(f===s?r:[ke(f),ke(d)]).some(g=>!X(u[g])&&u[g]!==i[g])})&&t.$reset()});l.observe(o,{attributes:!0,attributeFilter:a}),t._disconnect.push(()=>l.disconnect())}function me(t,e){var i;(i=t.$options[e])==null||i.forEach(s=>s.call(t))}function _s(t){t._connected||(Da(t),me(t,"beforeConnect"),t._connected=!0,t._disconnect=[],Pa(t),Gr(t),Ia(t),_a(t),Ba(t),Ca(t),me(t,"connected"),je(t))}function As(t){t._connected&&(me(t,"beforeDisconnect"),t._disconnect.forEach(e=>e()),t._disconnect=null,me(t,"disconnected"),t._connected=!1)}let Na=0;function Jn(t,e={}){e.data=Ha(e,t.constructor.options),t.$options=We(t.constructor.options,e,t),t.$props={},t._uid=Na++,za(t),Fa(t),Ea(t),me(t,"created"),e.el&&t.$mount(e.el)}function za(t){const{data:e={}}=t.$options;for(const i in e)t.$props[i]=t[i]=e[i]}function Fa(t){const{methods:e}=t.$options;if(e)for(const i in e)t[i]=e[i].bind(t)}function Ha({data:t={}},{args:e=[],props:i={}}){J(t)&&(t=t.slice(0,e.length).reduce((s,n,o)=>(Se(n)?ft(s,n):s[e[o]]=n,s),{}));for(const s in t)X(t[s])?delete t[s]:i[s]&&(t[s]=ms(i[s],t[s]));return t}const lt=function(t){Jn(this,t)};lt.util=Wr,lt.options={},lt.version="3.22.0";const La="uk-",Xt="__uikit__",ve={};function Kn(t,e){var i,s;const n=La+Bt(t);if(!e)return ve[n].options||(ve[n]=lt.extend(ve[n])),ve[n];t=ke(t),lt[t]=(r,a)=>Ye(t,r,a);const o=(i=e.options)!=null?i:{...e};return o.id=n,o.name=t,(s=o.install)==null||s.call(o,lt,o,t),lt._initialized&&!o.functional&&requestAnimationFrame(()=>Ye(t,`[${n}],[data-${n}]`)),ve[n]=o}function Ye(t,e,i,...s){const n=Kn(t);return n.options.functional?new n({data:Se(e)?e:[e,i,...s]}):e?D(e).map(o)[0]:o();function o(r){const a=Ti(r,t);if(a)if(i)a.$destroy();else return a;return new n({el:r,data:i})}}function Ge(t){return(t==null?void 0:t[Xt])||{}}function Ti(t,e){return Ge(t)[e]}function Wa(t,e){t[Xt]||(t[Xt]={}),t[Xt][e.$options.name]=e}function ja(t,e){var i;(i=t[Xt])==null||delete i[e.$options.name],ti(t[Xt])&&delete t[Xt]}function Ra(t){t.component=Kn,t.getComponents=Ge,t.getComponent=Ti,t.update=Zn,t.use=function(i){if(!i.installed)return i.call(null,this),i.installed=!0,this},t.mixin=function(i,s){s=(F(s)?this.component(s):s)||this,s.options=We(s.options,i)},t.extend=function(i){i||(i={});const s=this,n=function(r){Jn(this,r)};return n.prototype=Object.create(s.prototype),n.prototype.constructor=n,n.options=We(s.options,i),n.super=s,n.extend=s.extend,n};let e;Object.defineProperty(t,"container",{get(){return e||document.body},set(i){e=$(i)}})}function Zn(t,e){t=t?R(t):document.body;for(const i of he(t).reverse())Qn(i,e);_t(t,i=>Qn(i,e))}function Qn(t,e){const i=Ge(t);for(const s in i)je(i[s],e)}function qa(t){t.prototype.$mount=function(e){const i=this;Wa(e,i),i.$options.el=e,e.isConnected&&_s(i)},t.prototype.$destroy=function(e=!1){const i=this,{el:s}=i.$options;s&&As(i),me(i,"destroy"),ja(s,i),e&&Q(i.$el)},t.prototype.$create=Ye,t.prototype.$emit=function(e){je(this,e)},t.prototype.$update=function(e=this.$el,i){Zn(e,i)},t.prototype.$reset=function(){As(this),_s(this)},t.prototype.$getComponent=Ti,Object.defineProperties(t.prototype,{$el:{get(){return this.$options.el}},$container:Object.getOwnPropertyDescriptor(t,"container")})}let Ua=1;function Jt(t,e=null){return(e==null?void 0:e.id)||`${t.$options.id}-${Ua++}`}var Va={i18n:{next:"Next slide",previous:"Previous slide",slideX:"Slide %s",slideLabel:"%s of %s",role:"String"},data:{selNav:!1,role:"region"},computed:{nav:({selNav:t},e)=>$(t,e),navChildren(){return B(this.nav)},selNavItem:({attrItem:t})=>`[${t}],[data-${t}]`,navItems(t,e){return D(this.selNavItem,e)}},watch:{nav(t,e){p(t,"role","tablist"),this.padNavitems(),e&&this.$emit()},list(t){z(t,"ul")&&p(t,"role","presentation")},navChildren(t){p(t,"role","presentation"),this.padNavitems(),this.updateNav()},navItems(t){for(const e of t){const i=Z(e,this.attrItem),s=$("a,button",e)||e;let n,o=null;if(vt(i)){const r=$t(i),a=this.slides[r];a&&(a.id||(a.id=Jt(this,a)),o=a.id),n=this.t("slideX",k(i)+1),p(s,"role","tab")}else this.list&&(this.list.id||(this.list.id=Jt(this,this.list)),o=this.list.id),n=this.t(i);p(s,{"aria-controls":o,"aria-label":p(s,"aria-label")||n})}},slides(t){t.forEach((e,i)=>p(e,{role:this.nav?"tabpanel":"group","aria-label":this.t("slideLabel",i+1,this.length),"aria-roledescription":this.nav?null:"slide"})),this.padNavitems()}},connected(){p(this.$el,{role:this.role,"aria-roledescription":"carousel"})},update:[{write(){this.navItems.concat(this.nav).forEach(t=>t&&(t.hidden=!this.maxIndex)),this.updateNav()},events:["resize"]}],events:[{name:"click keydown",delegate:({selNavItem:t})=>t,filter:({parallax:t})=>!t,handler(t){t.target.closest("a,button")&&(t.type==="click"||t.keyCode===M.SPACE)&&(t.preventDefault(),this.show(Z(t.current,this.attrItem)))}},{name:"itemshow",handler(){this.updateNav()}},{name:"keydown",delegate:({selNavItem:t})=>t,filter:({parallax:t})=>!t,handler(t){const{current:e,keyCode:i}=t,s=Z(e,this.attrItem);if(!vt(s))return;let n=i===M.HOME?0:i===M.END?"last":i===M.LEFT?"previous":i===M.RIGHT?"next":-1;~n&&(t.preventDefault(),this.show(n))}}],methods:{updateNav(){const t=this.getValidIndex();for(const e of this.navItems){const i=Z(e,this.attrItem),s=$("a,button",e)||e;if(vt(i)){const o=$t(i)===t;H(e,this.clsActive,o),H(s,"uk-disabled",!!this.parallax),p(s,{"aria-selected":o,tabindex:o&&!this.parallax?null:-1}),o&&s&&C(O(e),":focus-within")&&s.focus()}else H(e,"uk-invisible",this.finite&&(i==="previous"&&t===0||i==="next"&&t>=this.maxIndex))}},padNavitems(){if(!this.nav)return;const t=[];for(let e=0;e<this.length;e++){const i=`${this.attrItem}="${e}"`;t[e]=this.navChildren.findLast(s=>s.matches(`[${i}]`))||$(`<li ${i}><a href></a></li>`)}Ce(t,this.navChildren)||bt(this.nav,t)}}};const Ya="cubic-bezier(0.25, 0.46, 0.45, 0.94)",Ga="cubic-bezier(0.165, 0.84, 0.44, 1)";var to={mixins:[$a,ka,Va,Si],props:{clsActivated:String,easing:String,index:Number,finite:Boolean,velocity:Number},data:()=>({easing:"ease",finite:!1,velocity:1,index:0,prevIndex:-1,stack:[],percent:0,clsActive:"uk-active",clsActivated:"",clsEnter:"uk-slide-enter",clsLeave:"uk-slide-leave",clsSlideActive:"uk-slide-active",Transitioner:!1,transitionOptions:{}}),connected(){this.prevIndex=-1,this.index=this.getValidIndex(this.$props.index),this.stack=[]},disconnected(){_(this.slides,this.clsActive)},computed:{duration:({velocity:t},e)=>eo(e.offsetWidth/t),list:({selList:t},e)=>$(t,e),maxIndex(){return this.length-1},slides(){return B(this.list)},length(){return this.slides.length}},watch:{slides(t,e){e&&this.$emit()}},events:{itemshow({target:t}){S(t,this.clsEnter,this.clsSlideActive)},itemshown({target:t}){_(t,this.clsEnter)},itemhide({target:t}){S(t,this.clsLeave)},itemhidden({target:t}){_(t,this.clsLeave,this.clsSlideActive)}},methods:{async show(t,e=!1){var i;if(this.dragging||!this.length||this.parallax)return;const{stack:s}=this,n=e?0:s.length,o=()=>{s.splice(n,1),s.length&&this.show(s.shift(),!0)};if(s[e?"unshift":"push"](t),!e&&s.length>1){s.length===2&&((i=this._transitioner)==null||i.forward(Math.min(this.duration,200)));return}const r=this.getIndex(this.index),a=x(this.slides,this.clsActive)&&this.slides[r],l=this.getIndex(t,this.index),c=this.slides[l];if(a===c){o();return}if(this.dir=Xa(t,r),this.prevIndex=r,this.index=l,a&&!v(a,"beforeitemhide",[this])||!v(c,"beforeitemshow",[this,a])){this.index=this.prevIndex,o();return}a&&v(a,"itemhide",[this]),v(c,"itemshow",[this]),await this._show(a,c,e),a&&v(a,"itemhidden",[this]),v(c,"itemshown",[this]),s.shift(),this._transitioner=null,s.length&&requestAnimationFrame(()=>s.length&&this.show(s.shift(),!0))},getIndex(t=this.index,e=this.index){return K(ot(t,this.slides,e,this.finite),0,Math.max(0,this.maxIndex))},getValidIndex(t=this.index,e=this.prevIndex){return this.getIndex(t,e)},async _show(t,e,i){if(this._transitioner=this._getTransitioner(t,e,this.dir,{easing:i?e.offsetWidth<600?Ya:Ga:this.easing,...this.transitionOptions}),!i&&!t){this._translate(1);return}const{length:s}=this.stack;return this._transitioner[s>1?"forward":"show"](s>1?Math.min(this.duration,75+75/(s-1)):this.duration,this.percent)},_translate(t,e=this.prevIndex,i=this.index){const s=this._getTransitioner(e===i?!1:e,i);return s.translate(t),s},_getTransitioner(t=this.prevIndex,e=this.index,i=this.dir||1,s=this.transitionOptions){return new this.Transitioner(Ee(t)?this.slides[t]:t,Ee(e)?this.slides[e]:e,i*(U?-1:1),s)}}};function Xa(t,e){return t==="next"?1:t==="previous"||t<e?-1:1}function eo(t){return .5*t+300}var io={mixins:[to],props:{animation:String},data:{animation:"slide",clsActivated:"uk-transition-active",Animations:Cs,Transitioner:xa},computed:{animation({animation:t,Animations:e}){return{...e[t]||e.slide,name:t}},transitionOptions(){return{animation:this.animation}}},observe:dt(),events:{itemshow({target:t}){S(t,this.clsActive)},itemshown({target:t}){S(t,this.clsActivated)},itemhidden({target:t}){_(t,this.clsActive,this.clsActivated)}}},Ja={...Cs,fade:{show(){return[{opacity:0,zIndex:0},{zIndex:-1}]},percent(t){return 1-h(t,"opacity")},translate(t){return[{opacity:1-t,zIndex:0},{zIndex:-1}]}},scale:{show(){return[{opacity:0,transform:be(1+.5),zIndex:0},{zIndex:-1}]},percent(t){return 1-h(t,"opacity")},translate(t){return[{opacity:1-t,transform:be(1+.5*t),zIndex:0},{zIndex:-1}]}},pull:{show(t){return t<0?[{transform:j(30),zIndex:-1},{transform:j(),zIndex:0}]:[{transform:j(-100),zIndex:0},{transform:j(),zIndex:-1}]},percent(t,e,i){return i<0?1-Ve(e):Ve(t)},translate(t,e){return e<0?[{transform:j(30*t),zIndex:-1},{transform:j(-100*(1-t)),zIndex:0}]:[{transform:j(-t*100),zIndex:0},{transform:j(30*(1-t)),zIndex:-1}]}},push:{show(t){return t<0?[{transform:j(100),zIndex:0},{transform:j(),zIndex:-1}]:[{transform:j(-30),zIndex:-1},{transform:j(),zIndex:0}]},percent(t,e,i){return i>0?1-Ve(e):Ve(t)},translate(t,e){return e<0?[{transform:j(t*100),zIndex:0},{transform:j(-30*(1-t)),zIndex:-1}]:[{transform:j(-30*t),zIndex:-1},{transform:j(100*(1-t)),zIndex:0}]}}};function be(t){return`scale3d(${t}, ${t}, 1)`}var so={...Cs,fade:{show(){return[{opacity:0},{opacity:1}]},percent(t){return 1-h(t,"opacity")},translate(t){return[{opacity:1-t},{opacity:t}]}},scale:{show(){return[{opacity:0,transform:be(1-.2)},{opacity:1,transform:be(1)}]},percent(t){return 1-h(t,"opacity")},translate(t){return[{opacity:1-t,transform:be(1-.2*t)},{opacity:t,transform:be(1-.2+.2*t)}]}}},no={i18n:{counter:"%s / %s"},mixins:[Es,io],functional:!0,props:{counter:Boolean,preload:Number,nav:Boolean,slidenav:Boolean,delayControls:Number,videoAutoplay:Boolean,template:String},data:()=>({counter:!1,preload:1,nav:!1,slidenav:!0,delayControls:3e3,videoAutoplay:!1,items:[],cls:"uk-open",clsPage:"uk-lightbox-page",clsFit:"uk-lightbox-items-fit",clsZoom:"uk-lightbox-zoom",attrItem:"uk-lightbox-item",selList:".uk-lightbox-items",selClose:".uk-close-large",selNav:".uk-lightbox-thumbnav, .uk-lightbox-dotnav",selCaption:".uk-lightbox-caption",selCounter:".uk-lightbox-counter",pauseOnHover:!1,velocity:2,Animations:so,template:'<div class="uk-lightbox uk-overflow-hidden"> <div class="uk-lightbox-items"></div> <div class="uk-position-top-right uk-position-small uk-transition-fade" uk-inverse> <button class="uk-lightbox-close uk-close-large" type="button" uk-close></button> </div> <div class="uk-lightbox-slidenav uk-position-center-left uk-position-medium uk-transition-fade" uk-inverse> <a href uk-slidenav-previous uk-lightbox-item="previous"></a> </div> <div class="uk-lightbox-slidenav uk-position-center-right uk-position-medium uk-transition-fade" uk-inverse> <a href uk-slidenav-next uk-lightbox-item="next"></a> </div> <div class="uk-position-center-right uk-position-medium uk-transition-fade" uk-inverse style="max-height: 90vh; overflow: auto;"> <ul class="uk-lightbox-thumbnav uk-lightbox-thumbnav-vertical uk-thumbnav uk-thumbnav-vertical"></ul> <ul class="uk-lightbox-dotnav uk-dotnav uk-dotnav-vertical"></ul> </div> <div class="uk-lightbox-counter uk-text-large uk-position-top-left uk-position-small uk-transition-fade" uk-inverse></div> <div class="uk-lightbox-caption uk-position-bottom uk-text-center uk-transition-slide-bottom uk-transition-opaque"></div> </div>'}),created(){let t=$(this.template);z(t,"template")&&(t=St(bt(t)));const e=$(this.selList,t),i=this.$props.nav;Q(D(this.selNav,t).filter(o=>!C(o,`.uk-${i}`)));for(const[o,r]of this.items.entries())W(e,"<div>"),i==="thumbnav"&&Ne(Ka(r,this.videoAutoplay),W($(this.selNav,t),`<li uk-lightbox-item="${o}"><a href></a></li>`));this.slidenav||Q(D(".uk-lightbox-slidenav",t)),this.counter||Q($(this.selCounter,t)),S(e,this.clsFit);const s=$("[uk-close]",t),n=this.t("close");s&&n&&(s.dataset.i18n=JSON.stringify({label:n})),this.$mount(W(this.container,t))},events:[{name:"click",self:!0,filter:({bgClose:t})=>t,delegate:({selList:t})=>`${t} > *`,handler(t){t.defaultPrevented||this.hide()}},{name:"click",self:!0,delegate:({clsZoom:t})=>`.${t}`,handler(t){t.defaultPrevented||H(this.list,this.clsFit)}},{name:`${oi} ${ut} keydown`,filter:({delayControls:t})=>t,handler(){this.showControls()}},{name:"shown",self:!0,handler(){this.showControls()}},{name:"hide",self:!0,handler(){this.hideControls(),_(this.slides,this.clsActive),N.stop(this.slides)}},{name:"hidden",self:!0,handler(){this.$destroy(!0)}},{name:"keyup",el:()=>document,handler({keyCode:t}){if(!this.isToggled(this.$el)||!this.draggable)return;let e=-1;t===M.LEFT?e="previous":t===M.RIGHT?e="next":t===M.HOME?e=0:t===M.END&&(e="last"),~e&&this.show(e)}},{name:"beforeitemshow",handler(t){bt($(this.selCaption,this.$el),this.getItem().caption||""),bt($(this.selCounter,this.$el),this.t("counter",this.index+1,this.slides.length));for(let e=-this.preload;e<=this.preload;e++)this.loadItem(this.index+e);this.isToggled()||(this.draggable=!1,t.preventDefault(),this.toggleElement(this.$el,!0,!1),this.animation=so.scale,_(t.target,this.clsActive),this.stack.splice(1,0,this.index))}},{name:"itemshown",handler(){this.draggable=this.$props.draggable}},{name:"itemload",async handler(t,e){const{source:i,type:s,attrs:n={}}=e;if(this.setItem(e,"<span uk-spinner uk-inverse></span>"),!i)return;let o;const r={allowfullscreen:"",style:"max-width: 100%; box-sizing: border-box;","uk-responsive":"","uk-video":`${!!this.videoAutoplay}`};if(s==="image"||oo(i)){const a=Dt("img");Nn(a,e.sources),p(a,{src:i,...ei(e,["alt","srcset","sizes"]),...n}),y(a,"load",()=>this.setItem(e,O(a)||a)),y(a,"error",()=>this.setError(e))}else if(s==="video"||ro(i)){const a=this.videoAutoplay==="inline",l=Dt("video",{src:i,playsinline:"",controls:a?null:"",loop:a?"":null,poster:this.videoAutoplay?null:e.poster,"uk-video":a?"automute: true":!!this.videoAutoplay,...n});y(l,"loadedmetadata",()=>this.setItem(e,l)),y(l,"error",()=>this.setError(e))}else if(s==="iframe"||i.match(/\.(html|php)($|\?)/i))this.setItem(e,Dt("iframe",{src:i,allowfullscreen:"",class:"uk-lightbox-iframe",...n}));else if(o=i.match(/\/\/(?:.*?youtube(-nocookie)?\..*?(?:[?&]v=|\/shorts\/)|youtu\.be\/)([\w-]{11})[&?]?(.*)?/))this.setItem(e,Dt("iframe",{src:`https://www.youtube${o[1]||""}.com/embed/${o[2]}${o[3]?`?${o[3]}`:""}`,width:1920,height:1080,...r,...n}));else if(o=i.match(/\/\/.*?vimeo\.[a-z]+\/(\d+)[&?]?(.*)?/))try{const{height:a,width:l}=await(await fetch(`https://vimeo.com/api/oembed.json?maxwidth=1920&url=${encodeURI(i)}`,{credentials:"omit"})).json();this.setItem(e,Dt("iframe",{src:`https://player.vimeo.com/video/${o[1]}${o[2]?`?${o[2]}`:""}`,width:l,height:a,...r,...n}))}catch{this.setError(e)}}},{name:"itemloaded",handler(){this.$emit("resize")}}],update:{read(){for(const t of D(`${this.selList} :not([controls]):is(img,video)`,this.$el))H(t,this.clsZoom,(t.naturalHeight||t.videoHeight)-this.$el.offsetHeight>Math.max(0,(t.naturalWidth||t.videoWidth)-this.$el.offsetWidth))},events:["resize"]},methods:{loadItem(t=this.index){const e=this.getItem(t);this.getSlide(e).childElementCount||v(this.$el,"itemload",[e])},getItem(t=this.index){return this.items[ot(t,this.slides)]},setItem(t,e){v(this.$el,"itemloaded",[this,bt(this.getSlide(t),e)])},getSlide(t){return this.slides[this.items.indexOf(t)]},setError(t){this.setItem(t,'<span uk-icon="icon: bolt; ratio: 2" uk-inverse></span>')},showControls(){clearTimeout(this.controlsTimer),this.controlsTimer=this.delayControls&&setTimeout(this.hideControls,this.delayControls),S(this.$el,"uk-active","uk-transition-active")},hideControls(){_(this.$el,"uk-active","uk-transition-active")}}};function Dt(t,e){const i=St(`<${t}>`);return p(i,e),i}function Ka(t,e){const i=t.poster||t.thumb&&(t.type==="image"||oo(t.thumb))?Dt("img",{src:t.poster||t.thumb,alt:""}):t.thumb&&(t.type==="video"||ro(t.thumb))?Dt("video",{src:t.thumb,loop:"",playsinline:"","uk-video":`autoplay: ${!!e}; automute: true`}):Dt("canvas");return t.thumbRatio&&(i.style.aspectRatio=t.thumbRatio),i}function oo(t){return t==null?void 0:t.match(/\.(avif|jpe?g|jfif|a?png|gif|svg|webp)($|\?)/i)}function ro(t){return t==null?void 0:t.match(/\.(mp4|webm|ogv)($|\?)/i)}const Za=".uk-disabled *, .uk-disabled, [disabled]";var Qa={install:tl,props:{toggle:String},data:{toggle:"a"},computed:{toggles:({toggle:t},e)=>D(t,e)},watch:{toggles(t){this.hide();for(const e of t)z(e,"a")&&p(e,"role","button")}},disconnected(){this.hide()},events:{name:"click",delegate:({toggle:t})=>t,handler(t){t.defaultPrevented||(t.preventDefault(),C(t.current,Za)||this.show(t.current))}},methods:{show(t){let e=this.toggles.map(ao);if(this.nav==="thumbnav"&&el.call(this,this.toggles,e),e=qs(e,"source"),se(t)){const{source:i}=ao(t);t=xt(e,({source:s})=>i===s)}return this.panel=this.panel||this.$create("lightboxPanel",{...this.$props,items:e}),y(this.panel.$el,"hidden",()=>this.panel=null),this.panel.show(t)},hide(){var t;return(t=this.panel)==null?void 0:t.hide()}}};function tl(t,e){t.lightboxPanel||t.component("lightboxPanel",no),ft(e.props,t.component("lightboxPanel").options.props)}function el(t,e){for(const[i,s]of Object.entries(t)){if(e[i].thumb)continue;const n=he(s).reverse().concat(s).find(r=>this.$el.contains(r)&&(r===s||D(this.toggle,r).length===1));if(!n)continue;const o=$("img,video",n);o&&(e[i].thumb=o.currentSrc||o.poster||o.src,e[i].thumbRatio=(o.naturalWidth||o.videoWidth)/(o.naturalHeight||o.videoHeight))}}function ao(t){const e={};for(const i of t.getAttributeNames()){const s=i.replace(/^data-/,"");e[s==="href"?"source":s]=t.getAttribute(i)}return e.attrs=pe(e.attrs),e}var il={mixins:[Ue],functional:!0,args:["message","status"],data:{message:"",status:"",timeout:5e3,group:"",pos:"top-center",clsContainer:"uk-notification",clsClose:"uk-notification-close",clsMsg:"uk-notification-message"},install:sl,computed:{marginProp:({pos:t})=>`margin-${t.match(/[a-z]+(?=-)/)[0]}`,startProps(){return{opacity:0,[this.marginProp]:-this.$el.offsetHeight}}},created(){const t=`${this.clsContainer}-${this.pos}`,e=`data-${this.clsContainer}-container`,i=$(`.${t}[${e}]`,this.container)||W(this.container,`<div class="${this.clsContainer} ${t}" ${e}></div>`);this.$mount(W(i,`<div class="${this.clsMsg}${this.status?` ${this.clsMsg}-${this.status}`:""}" role="alert"> <a href class="${this.clsClose}" data-uk-close></a> <div>${this.message}</div> </div>`))},async connected(){const t=k(h(this.$el,this.marginProp));await N.start(h(this.$el,this.startProps),{opacity:1,[this.marginProp]:t}),this.timeout&&(this.timer=setTimeout(this.close,this.timeout))},events:{click(t){t.target.closest('a[href="#"],a[href=""]')&&t.preventDefault(),this.close()},[jt](){this.timer&&clearTimeout(this.timer)},[le](){this.timeout&&(this.timer=setTimeout(this.close,this.timeout))}},methods:{async close(t){const e=i=>{const s=O(i);v(i,"close",[this]),Q(i),s!=null&&s.hasChildNodes()||Q(s)};this.timer&&clearTimeout(this.timer),t||await N.start(this.$el,this.startProps),e(this.$el)}}};function sl(t){t.notification.closeAll=function(e,i){_t(document.body,s=>{const n=t.getComponent(s,"notification");n&&(!e||e===n.group)&&n.close(i)})}}var Ei={props:{media:Boolean},data:{media:!1},connected(){const t=nl(this.media,this.$el);if(this.matchMedia=!0,t){this.mediaObj=window.matchMedia(t);const e=()=>{this.matchMedia=this.mediaObj.matches,v(this.$el,ue("mediachange",!1,!0,[this.mediaObj]))};this.offMediaObj=y(this.mediaObj,"change",()=>{e(),this.$emit("resize")}),e()}},disconnected(){var t;(t=this.offMediaObj)==null||t.call(this)}};function nl(t,e){if(F(t)){if(mt(t,"@"))t=k(h(e,`--uk-breakpoint-${t.slice(1)}`));else if(isNaN(t))return t}return t&&vt(t)?`(min-width: ${t}px)`:""}function lo(t){return q(t)?Math.ceil(Math.max(0,...D("[stroke]",t).map(e=>{var i;return((i=e.getTotalLength)==null?void 0:i.call(e))||0}))):0}const Ci={x:Pi,y:Pi,rotate:Pi,scale:Pi,color:Os,backgroundColor:Os,borderColor:Os,blur:Kt,hue:Kt,fopacity:Kt,grayscale:Kt,invert:Kt,saturate:Kt,sepia:Kt,opacity:rl,stroke:al,bgx:uo,bgy:uo},{keys:ho}=Object;var co={mixins:[Ei],props:vo(ho(Ci),"list"),data:vo(ho(Ci),void 0),computed:{props(t,e){const i={};for(const n in t)n in Ci&&!X(t[n])&&(i[n]=t[n].slice());const s={};for(const n in i)s[n]=Ci[n](n,e,i[n],i);return s}},events:{load(){this.$emit()}},methods:{reset(){for(const t in this.getCss(0))h(this.$el,t,"")},getCss(t){const e={};for(const i in this.props)this.props[i](e,K(t));return e.willChange=Object.keys(e).map(hi).join(","),e}}};function Pi(t,e,i){let s=Ai(i)||{x:"px",y:"px",rotate:"deg"}[t]||"",n;return t==="x"||t==="y"?(t=`translate${Nt(t)}`,n=o=>k(k(o).toFixed(s==="px"?0:6))):t==="scale"&&(s="",n=o=>{var r;return Ai([o])?G(o,"width",e,!0)/e[`offset${(r=o.endsWith)!=null&&r.call(o,"vh")?"Height":"Width"}`]:k(o)}),i.length===1&&i.unshift(t==="scale"?1:0),i=we(i,n),(o,r)=>{o.transform=`${o.transform||""} ${t}(${Xe(i,r)}${s})`}}function Os(t,e,i){return i.length===1&&i.unshift(Je(e,t,"")),i=we(i,s=>ol(e,s)),(s,n)=>{const[o,r,a]=mo(i,n),l=o.map((c,u)=>(c+=a*(r[u]-c),u===3?k(c):parseInt(c,10))).join(",");s[t]=`rgba(${l})`}}function ol(t,e){return Je(t,"color",e).split(/[(),]/g).slice(1,-1).concat(1).slice(0,4).map(k)}function Kt(t,e,i){i.length===1&&i.unshift(0);const s=Ai(i)||{blur:"px",hue:"deg"}[t]||"%";return t={fopacity:"opacity",hue:"hue-rotate"}[t]||t,i=we(i),(n,o)=>{const r=Xe(i,o);n.filter=`${n.filter||""} ${t}(${r+s})`}}function rl(t,e,i){return i.length===1&&i.unshift(Je(e,t,"")),i=we(i),(s,n)=>{s[t]=Xe(i,n)}}function al(t,e,i){i.length===1&&i.unshift(0);const s=Ai(i),n=lo(e);return i=we(i.reverse(),o=>(o=k(o),s==="%"?o*n/100:o)),i.some(([o])=>o)?(h(e,"strokeDasharray",n),(o,r)=>{o.strokeDashoffset=Xe(i,r)}):A}function uo(t,e,i,s){i.length===1&&i.unshift(0);const n=t==="bgy"?"height":"width";s[t]=we(i,a=>G(a,n,e));const o=["bgx","bgy"].filter(a=>a in s);if(o.length===2&&t==="bgx")return A;if(Je(e,"backgroundSize","")==="cover")return ll(t,e,i,s);const r={};for(const a of o)r[a]=fo(e,a);return po(o,r,s)}function ll(t,e,i,s){const n=hl(e);if(!n.width)return A;const o={width:e.offsetWidth,height:e.offsetHeight},r=["bgx","bgy"].filter(u=>u in s),a={};for(const u of r){const d=s[u].map(([P])=>P),f=Math.min(...d),g=Math.max(...d),w=d.indexOf(f)<d.indexOf(g),I=g-f;a[u]=`${(w?-I:0)-(w?f:g)}px`,o[u==="bgy"?"height":"width"]+=I}const l=Ri.cover(n,o);for(const u of r){const d=u==="bgy"?"height":"width",f=l[d]-o[d];a[u]=`max(${fo(e,u)},-${f}px) + ${a[u]}`}const c=po(r,a,s);return(u,d)=>{c(u,d),u.backgroundSize=`${l.width}px ${l.height}px`,u.backgroundRepeat="no-repeat"}}function fo(t,e){return Je(t,`background-position-${e.slice(-1)}`,"")}function po(t,e,i){return function(s,n){for(const o of t){const r=Xe(i[o],n);s[`background-position-${o.slice(-1)}`]=`calc(${e[o]} + ${r}px)`}}}const go={},_i={};function hl(t){const e=h(t,"backgroundImage").replace(/^none|url\(["']?(.+?)["']?\)$/,"$1");if(_i[e])return _i[e];const i=new Image;return e&&(i.src=e,!i.naturalWidth&&!go[e])?(L(i,"error load",()=>{_i[e]=Ds(i),v(t,ue("load",!1))}),go[e]=!0,Ds(i)):_i[e]=Ds(i)}function Ds(t){return{width:t.naturalWidth,height:t.naturalHeight}}function we(t,e=k){const i=[],{length:s}=t;let n=0;for(let o=0;o<s;o++){let[r,a]=F(t[o])?t[o].trim().split(/ (?![^(]*\))/):[t[o]];if(r=e(r),a=a?k(a)/100:null,o===0?a===null?a=0:a&&i.push([r,0]):o===s-1&&(a===null?a=1:a!==1&&(i.push([r,a]),a=1)),i.push([r,a]),a===null)n++;else if(n){const l=i[o-n-1][1],c=(a-l)/(n+1);for(let u=n;u>0;u--)i[o-u][1]=l+c*(n-u+1);n=0}}return i}function mo(t,e){const i=xt(t.slice(1),([,s])=>e<=s)+1;return[t[i-1][0],t[i][0],(e-t[i-1][1])/(t[i][1]-t[i-1][1])]}function Xe(t,e){const[i,s,n]=mo(t,e);return i+Math.abs(i-s)*n*(i<s?1:-1)}const cl=/^-?\d+(?:\.\d+)?(\S+)?/;function Ai(t,e){var i;for(const s of t){const n=(i=s.match)==null?void 0:i.call(s,cl);if(n)return n[1]}return e}function Je(t,e,i){const s=t.style[e],n=h(h(t,e,i),e);return t.style[e]=s,n}function vo(t,e){return t.reduce((i,s)=>(i[s]=e,i),{})}function bo(t,e){return e>=0?Math.pow(t,e+1):1-Math.pow(1-t,1-e)}var ul={mixins:[co],props:{target:String,viewport:Number,easing:Number,start:String,end:String},data:{target:!1,viewport:1,easing:1,start:0,end:0},computed:{target:({target:t},e)=>wo(t&&tt(t,e)||e),start({start:t}){return G(t,"height",this.target,!0)},end({end:t,viewport:e}){return G(t||(e=(1-e)*100)&&`${e}vh+${e}%`,"height",this.target,!0)}},observe:[vs(),Re({target:({target:t})=>t}),dt({target:({$el:t,target:e})=>[t,e,Ot(e,!0)]})],update:{read({percent:t},e){if(e.has("scroll")||(t=!1),!q(this.$el))return!1;if(!this.matchMedia)return;const i=t;return t=bo(wi(this.target,this.start,this.end),this.easing),{percent:t,style:i===t?!1:this.getCss(t)}},write({style:t}){if(!this.matchMedia){this.reset();return}t&&h(this.$el,t)},events:["scroll","resize"]}};function wo(t){return t?"offsetTop"in t?t:wo(O(t)):document.documentElement}var xo={props:{parallax:Boolean,parallaxTarget:Boolean,parallaxStart:String,parallaxEnd:String,parallaxEasing:Number},data:{parallax:!1,parallaxTarget:!1,parallaxStart:0,parallaxEnd:0,parallaxEasing:0},observe:[dt({target:({$el:t,parallaxTarget:e})=>[t,e],filter:({parallax:t})=>t}),Re({filter:({parallax:t})=>t})],computed:{parallaxTarget({parallaxTarget:t},e){return t&&tt(t,e)||this.list}},update:{read(){if(!this.parallax)return!1;const t=this.parallaxTarget;if(!t)return!1;const e=G(this.parallaxStart,"height",t,!0),i=G(this.parallaxEnd,"height",t,!0),s=bo(wi(t,e,i),this.parallaxEasing);return{parallax:this.getIndexAt(s)}},write({parallax:t}){const[e,i]=t,s=this.getValidIndex(e+Math.ceil(i)),n=this.slides[e],o=this.slides[s],{triggerShow:r,triggerShown:a,triggerHide:l,triggerHidden:c}=dl(this);if(~this.prevIndex)for(const d of new Set([this.index,this.prevIndex]))b([s,e],d)||(l(this.slides[d]),c(this.slides[d]));const u=this.prevIndex!==e||this.index!==s;this.dir=1,this.prevIndex=e,this.index=s,n!==o&&l(n),r(o),u&&a(n),this._translate(n===o?1:i,n,o)},events:["scroll","resize"]},methods:{getIndexAt(t){const e=t*(this.length-1);return[Math.floor(e),e%1]}}};function dl(t){const{clsSlideActive:e,clsEnter:i,clsLeave:s}=t;return{triggerShow:n,triggerShown:o,triggerHide:r,triggerHidden:a};function n(l){x(l,s)&&(r(l),a(l)),x(l,e)||(v(l,"beforeitemshow",[t]),v(l,"itemshow",[t]))}function o(l){x(l,i)&&v(l,"itemshown",[t])}function r(l){x(l,e)||n(l),x(l,i)&&o(l),x(l,s)||(v(l,"beforeitemhide",[t]),v(l,"itemhide",[t]))}function a(l){x(l,s)&&v(l,"itemhidden",[t])}}var $o={update:{write(){if(this.stack.length||this.dragging||this.parallax)return;const t=this.getValidIndex();!~this.prevIndex||this.index!==t?this.show(t):this._translate(1)},events:["resize"]}},yo={observe:yi({target:({slides:t})=>t,targets:t=>t.getAdjacentSlides()}),methods:{getAdjacentSlides(){return[1,-1].map(t=>this.slides[this.getIndex(this.index+t)])}}};function fl(t,e,i,{center:s,easing:n,list:o}){const r=t?Ke(t,o,s):Ke(e,o,s)+m(e).width*i,a=e?Ke(e,o,s):r+m(t).width*i*(U?-1:1),{promise:l,resolve:c}=Ln();return{dir:i,show(u,d=0,f){const g=f?"linear":n;return u-=Math.round(u*K(d,-1,1)),h(o,"transitionProperty","none"),this.translate(d),h(o,"transitionProperty",""),d=t?d:K(d,0,1),Gt(this.getItemIn(),"itemin",{percent:d,duration:u,timing:g,dir:i}),t&&Gt(this.getItemIn(!0),"itemout",{percent:1-d,duration:u,timing:g,dir:i}),N.start(o,{transform:j(-a*(U?-1:1),"px")},u,g).then(c,A),l},cancel(){return N.cancel(o)},reset(){h(o,"transform","")},async forward(u,d=this.percent()){return await this.cancel(),this.show(u,d,!0)},translate(u){if(u===this.percent())return;const d=this.getDistance()*i*(U?-1:1);h(o,"transform",j(K(-a+(d-d*u),-xe(o),m(o).width)*(U?-1:1),"px"));const f=this.getActives(),g=this.getItemIn(),w=this.getItemIn(!0);u=t?K(u,-1,1):0;for(const I of B(o)){const P=b(f,I),ht=I===g,It=I===w,Mt=ht||!It&&(P||i*(U?-1:1)===-1^Oi(I,o)>Oi(t||e));Gt(I,`itemtranslate${Mt?"in":"out"}`,{dir:i,percent:It?1-u:ht?u:P?1:0})}},percent(){return Math.abs((new DOMMatrix(h(o,"transform")).m41*(U?-1:1)+r)/(a-r))},getDistance(){return Math.abs(a-r)},getItemIn(u=!1){let d=this.getActives(),f=So(o,Ke(e||t,o,s));if(u){const g=d;d=f,f=g}return f[xt(f,g=>!b(d,g))]},getActives(){return So(o,Ke(t||e,o,s))}}}function Ke(t,e,i){const s=Oi(t,e);return i?s-pl(t,e):Math.min(s,ko(e))}function ko(t){return Math.max(0,xe(t)-m(t).width)}function xe(t,e){return Ht(B(t).slice(0,e),i=>m(i).width)}function pl(t,e){return m(e).width/2-m(t).width/2}function Oi(t,e){return t&&(es(t).left+(U?m(t).width-m(e).width:0))*(U?-1:1)||0}function So(t,e){e-=1;const i=m(t).width,s=e+i+2;return B(t).filter(n=>{const o=Oi(n,t),r=o+Math.min(m(n).width,i);return o>=e&&r<=s})}var gl={mixins:[it,to,$o,xo,yo],props:{center:Boolean,sets:Boolean,active:String},data:{center:!1,sets:!1,attrItem:"uk-slider-item",selList:".uk-slider-items",selNav:".uk-slider-nav",clsContainer:"uk-slider-container",active:"all",Transitioner:fl},computed:{finite({finite:t}){return t||ml(this.list,this.center)},maxIndex(){if(!this.finite||this.center&&!this.sets)return this.length-1;if(this.center)return Ft(this.sets);let t=0;const e=ko(this.list),i=xt(this.slides,s=>{if(t>=e-.005)return!0;t+=m(s).width});return~i?i:this.length-1},sets({sets:t}){if(!t||this.parallax)return;let e=0;const i=[],s=m(this.list).width;for(let n=0;n<this.length;n++){const o=m(this.slides[n]).width;e+o>s&&(e=0),this.center?e<s/2&&e+o+m(this.slides[ot(n+1,this.slides)]).width/2>s/2&&(i.push(n),e=s/2-o/2):e===0&&i.push(Math.min(n,this.maxIndex)),e+=o}if(i.length)return i},transitionOptions(){return{center:this.center,list:this.list}},slides(){return B(this.list).filter(q)}},connected(){H(this.$el,this.clsContainer,!$(`.${this.clsContainer}`,this.$el))},observe:dt({target:({slides:t,$el:e})=>[e,...t]}),update:{write(){for(const t of this.navItems){const e=$t(Z(t,this.attrItem));e!==!1&&(t.hidden=!this.maxIndex||e>this.maxIndex||this.sets&&!b(this.sets,e))}this.reorder(),this.parallax||this._translate(1),this.updateActiveClasses()},events:["resize"]},events:{beforeitemshow(t){!this.dragging&&this.sets&&this.stack.length<2&&!b(this.sets,this.index)&&(this.index=this.getValidIndex());const e=Math.abs(this.index-this.prevIndex+(this.dir>0&&this.index<this.prevIndex||this.dir<0&&this.index>this.prevIndex?(this.maxIndex+1)*this.dir:0));if(!this.dragging&&e>1){for(let n=0;n<e;n++)this.stack.splice(1,0,this.dir>0?"next":"previous");t.preventDefault();return}const i=this.dir<0||!this.slides[this.prevIndex]?this.index:this.prevIndex,s=xe(this.list)/this.length;this.duration=eo(s/this.velocity)*(m(this.slides[i]).width/s),this.reorder()},itemshow(){~this.prevIndex&&S(this._getTransitioner().getItemIn(),this.clsActive),this.updateActiveClasses(this.prevIndex)},itemshown(){this.updateActiveClasses()}},methods:{reorder(){if(this.finite){h(this.slides,"order","");return}const t=this.dir>0&&this.slides[this.prevIndex]?this.prevIndex:this.index;if(this.slides.forEach((n,o)=>h(n,"order",this.dir>0&&o<t?1:this.dir<0&&o>=this.index?-1:"")),!this.center||!this.length)return;const e=this.slides[t];let i=m(this.list).width/2-m(e).width/2,s=0;for(;i>0;){const n=this.getIndex(--s+t,t),o=this.slides[n];h(o,"order",n>t?-2:-1),i-=m(o).width}},updateActiveClasses(t=this.index){let e=this._getTransitioner(t).getActives();this.active!=="all"&&(e=[this.slides[this.getValidIndex(t)]]);const i=[this.clsActive,!this.sets||b(this.sets,k(this.index))?this.clsActivated:""];for(const s of this.slides){const n=b(e,s);H(s,i,n),p(s,"aria-hidden",!n);for(const o of D(Ae,s))gt(o,"_tabindex")||(o._tabindex=p(o,"tabindex")),p(o,"tabindex",n?o._tabindex:-1)}},getValidIndex(t=this.index,e=this.prevIndex){if(t=this.getIndex(t,e),!this.sets)return t;let i;do{if(b(this.sets,t))return t;i=t,t=this.getIndex(t+this.dir,e)}while(t!==i);return t},getAdjacentSlides(){const{width:t}=m(this.list),e=-t,i=t*2,s=m(this.slides[this.index]).width,n=this.center?t/2-s/2:0,o=new Set;for(const r of[-1,1]){let a=n+(r>0?s:0),l=0;do{const c=this.slides[this.getIndex(this.index+r+l++*r)];a+=m(c).width*r,o.add(c)}while(this.length>l&&a>e&&a<i)}return Array.from(o)},getIndexAt(t){let e=-1;const i=this.center?xe(this.list)-(m(this.slides[0]).width/2+m(Ft(this.slides)).width/2):xe(this.list,this.maxIndex);let s=t*i,n=0;do{const o=m(this.slides[++e]).width,r=this.center?o/2+m(this.slides[e+1]).width/2:o;n=s/r%1,s-=r}while(s>=0&&e<this.maxIndex);return[e,n]}}};function ml(t,e){if(!t||t.length<2)return!0;const{width:i}=m(t);if(!e)return Math.ceil(xe(t))<Math.trunc(i+vl(t));const s=B(t),n=Math.trunc(i/2);for(const o in s){const r=s[o],a=m(r).width,l=new Set([r]);let c=0;for(const u of[-1,1]){let d=a/2,f=0;for(;d<n;){const g=s[ot(+o+u+f++*u,s)];if(l.has(g))return!0;d+=m(g).width,l.add(g)}c=Math.max(c,a/2+m(s[ot(+o+u,s)]).width/2-(d-n))}if(Math.trunc(c)>Ht(s.filter(u=>!l.has(u)),u=>m(u).width))return!0}return!1}function vl(t){return Math.max(0,...B(t).map(e=>m(e).width))}var Io={mixins:[co],beforeConnect(){this.item=this.$el.closest(`.${this.$options.id.replace("parallax","items")} > *`)},disconnected(){this.item=null},events:[{name:"itemin itemout",self:!0,el:({item:t})=>t,handler({type:t,detail:{percent:e,duration:i,timing:s,dir:n}}){At.read(()=>{if(!this.matchMedia)return;const o=this.getCss(Eo(t,n,e)),r=this.getCss(To(t)?.5:n>0?1:0);At.write(()=>{h(this.$el,o),N.start(this.$el,r,i,s).catch(A)})})}},{name:"transitioncanceled transitionend",self:!0,el:({item:t})=>t,handler(){N.cancel(this.$el)}},{name:"itemtranslatein itemtranslateout",self:!0,el:({item:t})=>t,handler({type:t,detail:{percent:e,dir:i}}){At.read(()=>{if(!this.matchMedia){this.reset();return}const s=this.getCss(Eo(t,i,e));At.write(()=>h(this.$el,s))})}}]};function To(t){return ee(t,"in")}function Eo(t,e,i){return i/=2,To(t)^e<0?i:1-i}var bl={mixins:[it,io,$o,xo,yo],props:{ratio:String,minHeight:String,maxHeight:String},data:{ratio:"16:9",minHeight:void 0,maxHeight:void 0,selList:".uk-slideshow-items",attrItem:"uk-slideshow-item",selNav:".uk-slideshow-nav",Animations:Ja},watch:{list(t){h(t,{aspectRatio:this.ratio?this.ratio.replace(":","/"):void 0,minHeight:this.minHeight,maxHeight:this.maxHeight,width:"100%"})}},methods:{getAdjacentSlides(){return[1,-1].map(t=>this.slides[this.getIndex(this.index+t)])}}},wl={mixins:[it,On],props:{group:String,threshold:Number,clsItem:String,clsPlaceholder:String,clsDrag:String,clsDragState:String,clsBase:String,clsNoDrag:String,clsEmpty:String,clsCustom:String,handle:String},data:{group:!1,threshold:5,clsItem:"uk-sortable-item",clsPlaceholder:"uk-sortable-placeholder",clsDrag:"uk-sortable-drag",clsDragState:"uk-drag",clsBase:"uk-sortable",clsNoDrag:"uk-sortable-nodrag",clsEmpty:"uk-sortable-empty",clsCustom:"",handle:!1,pos:{}},events:{name:ut,passive:!1,handler(t){this.init(t)}},computed:{target:(t,e)=>(e.tBodies||[e])[0],items(){return B(this.target)},isEmpty(){return!this.items.length},handles({handle:t},e){return t?D(t,e):this.items}},watch:{isEmpty(t){H(this.target,this.clsEmpty,t)},handles(t,e){h(e,{touchAction:"",userSelect:""}),h(t,{touchAction:"none",userSelect:"none"})}},update:{write(t){if(!this.drag||!O(this.placeholder))return;const{pos:{x:e,y:i},origin:{offsetTop:s,offsetLeft:n},placeholder:o}=this;h(this.drag,{top:i-s,left:e-n});const r=this.getSortable(document.elementFromPoint(e,i));if(!r)return;const{items:a}=r;if(a.some(N.inProgress))return;const l=kl(a,{x:e,y:i});if(a.length&&(!l||l===o))return;const c=this.getSortable(o),u=Sl(r.target,l,o,e,i,r===c&&t.moved!==l);u!==!1&&(u&&o===u||(r!==c?(c.remove(o),t.moved=l):delete t.moved,r.insert(o,u),this.touched.add(r)))},events:["move"]},methods:{init(t){const{target:e,button:i,defaultPrevented:s}=t,[n]=this.items.filter(o=>o.contains(e));!n||s||i>0||ai(e)||e.closest(`.${this.clsNoDrag}`)||this.handle&&!e.closest(this.handle)||(t.preventDefault(),this.pos=kt(t),this.touched=new Set([this]),this.placeholder=n,this.origin={target:e,index:yt(n),...this.pos},y(document,oi,this.move),y(document,Ct,this.end),this.threshold||this.start(t))},start(t){this.drag=yl(this.$container,this.placeholder);const{left:e,top:i}=m(this.placeholder);ft(this.origin,{offsetLeft:this.pos.x-e,offsetTop:this.pos.y-i}),S(this.drag,this.clsDrag,this.clsCustom),S(this.placeholder,this.clsPlaceholder),S(this.items,this.clsItem),S(document.documentElement,this.clsDragState),v(this.$el,"start",[this,this.placeholder]),xl(this.pos),this.move(t)},move:Tl(function(t){ft(this.pos,kt(t)),!this.drag&&(Math.abs(this.pos.x-this.origin.x)>this.threshold||Math.abs(this.pos.y-this.origin.y)>this.threshold)&&this.start(t),this.$emit("move")}),end(){if(Rt(document,oi,this.move),Rt(document,Ct,this.end),!this.drag)return;$l();const t=this.getSortable(this.placeholder);this===t?this.origin.index!==yt(this.placeholder)&&v(this.$el,"moved",[this,this.placeholder]):(v(t.$el,"added",[t,this.placeholder]),v(this.$el,"removed",[this,this.placeholder])),v(this.$el,"stop",[this,this.placeholder]),Q(this.drag),this.drag=null;for(const{clsPlaceholder:e,clsItem:i}of this.touched)for(const s of this.touched)_(s.items,e,i);this.touched=null,_(document.documentElement,this.clsDragState)},insert(t,e){S(this.items,this.clsItem),e&&e.previousElementSibling!==t?this.animate(()=>ui(e,t)):!e&&this.target.lastElementChild!==t&&this.animate(()=>W(this.target,t))},remove(t){this.target.contains(t)&&this.animate(()=>Q(t))},getSortable(t){do{const e=this.$getComponent(t,"sortable");if(e&&(e===this||this.group!==!1&&e.group===this.group))return e}while(t=O(t))}}};let Co;function xl(t){let e=Date.now();Co=setInterval(()=>{let{x:i,y:s}=t;s+=document.scrollingElement.scrollTop;const n=(Date.now()-e)*.3;e=Date.now(),Ut(document.elementFromPoint(i,t.y)).reverse().some(o=>{let{scrollTop:r,scrollHeight:a}=o;const{top:l,bottom:c,height:u}=rt(o);if(l<s&&l+35>s)r-=n;else if(c>s&&c-35<s)r+=n;else return;if(r>0&&r<a-u)return o.scrollTop=r,!0})},15)}function $l(){clearInterval(Co)}function yl(t,e){let i;if(z(e,"li","tr")){i=$("<div>"),W(i,e.cloneNode(!0).children);for(const s of e.getAttributeNames())p(i,s,e.getAttribute(s))}else i=e.cloneNode(!0);return W(t,i),h(i,"margin","0","important"),h(i,{boxSizing:"border-box",width:e.offsetWidth,height:e.offsetHeight,padding:h(e,"padding")}),et(i.firstElementChild,et(e.firstElementChild)),i}function kl(t,e){return t[xt(t,i=>si(e,m(i)))]}function Sl(t,e,i,s,n,o){if(!B(t).length)return;const r=m(e);if(!o)return Il(t,i)||n<r.top+r.height/2?e:e.nextElementSibling;const a=m(i),l=Po([r.top,r.bottom],[a.top,a.bottom]),[c,u,d,f]=l?[s,"width","left","right"]:[n,"height","top","bottom"],g=a[u]<r[u]?r[u]-a[u]:0;return a[d]<r[d]?g&&c<r[d]+g?!1:e.nextElementSibling:g&&c>r[f]-g?!1:e}function Il(t,e){const i=B(t).length===1;i&&W(t,e);const s=B(t),n=s.some((o,r)=>{const a=m(o);return s.slice(r+1).some(l=>{const c=m(l);return!Po([a.left,a.right],[c.left,c.right])})});return i&&Q(e),n}function Po(t,e){return t[1]>e[0]&&e[1]>t[0]}function Tl(t){let e;return function(...i){e||(e=!0,t.call(this,...i),requestAnimationFrame(()=>e=!1))}}var El={mixins:[Ue,Yt,Fn],data:{pos:"top",animation:["uk-animation-scale-up"],duration:100,cls:"uk-active"},connected(){Cl(this.$el)},disconnected(){this.hide()},methods:{show(){if(this.isToggled(this.tooltip||null))return;const{delay:t=0,title:e}=_l(this.$options);if(!e)return;const i=p(this.$el,"title"),s=y(this.$el,["blur",le],o=>!pt(o)&&this.hide());this.reset=()=>{p(this.$el,{title:i,"aria-describedby":null}),s()};const n=Jt(this);p(this.$el,{title:null,"aria-describedby":n}),clearTimeout(this.showTimer),this.showTimer=setTimeout(()=>this._show(e,n),t)},async hide(){var t;C(this.$el,"input:focus")||(clearTimeout(this.showTimer),this.isToggled(this.tooltip||null)&&await this.toggleElement(this.tooltip,!1,!1),(t=this.reset)==null||t.call(this),Q(this.tooltip),this.tooltip=null)},async _show(t,e){this.tooltip=W(this.container,`<div id="${e}" class="uk-${this.$options.name}" role="tooltip"> <div class="uk-${this.$options.name}-inner">${t}</div> </div>`),y(this.tooltip,"toggled",(i,s)=>{if(!s)return;const n=()=>this.positionAt(this.tooltip,this.$el);n();const[o,r]=Pl(this.tooltip,this.$el,this.pos);this.origin=this.axis==="y"?`${gi(o)}-${r}`:`${r}-${gi(o)}`;const a=[L(document,`keydown ${ut}`,this.hide,!1,l=>l.type===ut&&!this.$el.contains(l.target)||l.type==="keydown"&&l.keyCode===M.ESC),y([document,...Vt(this.$el)],"scroll",n,{passive:!0})];L(this.tooltip,"hide",()=>a.forEach(l=>l()),{self:!0})}),await this.toggleElement(this.tooltip,!0)||this.hide()}},events:{[`focus ${jt} ${ut}`](t){(!pt(t)||t.type===ut)&&document.readyState!=="loading"&&this.show()}}};function Cl(t){li(t)||p(t,"tabindex","0")}function Pl(t,e,[i,s]){const n=E(t),o=E(e),r=[["left","right"],["top","bottom"]];for(const l of r){if(n[l[0]]>=o[l[1]]){i=l[1];break}if(n[l[1]]<=o[l[0]]){i=l[0];break}}return s=(b(r[0],i)?r[1]:r[0]).find(l=>n[l]===o[l])||"center",[i,s]}function _l(t){const{el:e,id:i,data:s}=t;return["delay","title"].reduce((n,o)=>({[o]:Z(e,o),...n}),{...pe(Z(e,i),["title"]),...s})}var Al={mixins:[Si],i18n:{invalidMime:"Invalid File Type: %s",invalidName:"Invalid File Name: %s",invalidSize:"Invalid File Size: %s Kilobytes Max"},props:{allow:String,clsDragover:String,concurrent:Number,maxSize:Number,method:String,mime:String,multiple:Boolean,name:String,params:Object,type:String,url:String},data:{allow:!1,clsDragover:"uk-dragover",concurrent:1,maxSize:0,method:"POST",mime:!1,multiple:!1,name:"files[]",params:{},type:"",url:"",abort:A,beforeAll:A,beforeSend:A,complete:A,completeAll:A,error:A,fail:A,load:A,loadEnd:A,loadStart:A,progress:A},events:{change(t){C(t.target,'input[type="file"]')&&(t.preventDefault(),t.target.files&&this.upload(t.target.files),t.target.value="")},drop(t){Di(t);const e=t.dataTransfer;e!=null&&e.files&&(_(this.$el,this.clsDragover),this.upload(e.files))},dragenter(t){Di(t)},dragover(t){Di(t),S(this.$el,this.clsDragover)},dragleave(t){Di(t),_(this.$el,this.clsDragover)}},methods:{async upload(t){if(t=ie(t),!t.length)return;v(this.$el,"upload",[t]);for(const s of t){if(this.maxSize&&this.maxSize*1e3<s.size){this.fail(this.t("invalidSize",this.maxSize));return}if(this.allow&&!_o(this.allow,s.name)){this.fail(this.t("invalidName",this.allow));return}if(this.mime&&!_o(this.mime,s.type)){this.fail(this.t("invalidMime",this.mime));return}}this.multiple||(t=t.slice(0,1)),this.beforeAll(this,t);const e=Ol(t,this.concurrent),i=async s=>{const n=new FormData;s.forEach(o=>n.append(this.name,o));for(const o in this.params)n.append(o,this.params[o]);try{const o=await Dl(this.url,{data:n,method:this.method,responseType:this.type,beforeSend:r=>{const{xhr:a}=r;y(a.upload,"progress",this.progress);for(const l of["loadStart","load","loadEnd","abort"])y(a,l.toLowerCase(),this[l]);return this.beforeSend(r)}});this.complete(o),e.length?await i(e.shift()):this.completeAll(o)}catch(o){this.error(o)}};await i(e.shift())}}};function _o(t,e){return e.match(new RegExp(`^${t.replace(/\//g,"\\/").replace(/\*\*/g,"(\\/[^\\/]+)*").replace(/\*/g,"[^\\/]+").replace(/((?!\\))\?/g,"$1.")}$`,"i"))}function Ol(t,e){const i=[];for(let s=0;s<t.length;s+=e)i.push(t.slice(s,s+e));return i}function Di(t){t.preventDefault(),t.stopPropagation()}async function Dl(t,e){const i={data:null,method:"GET",headers:{},xhr:new XMLHttpRequest,beforeSend:A,responseType:"",...e};return await i.beforeSend(i),Ml(t,i)}function Ml(t,e){return new Promise((i,s)=>{const{xhr:n}=e;for(const o in e)if(o in n)try{n[o]=e[o]}catch{}n.open(e.method.toUpperCase(),t);for(const o in e.headers)n.setRequestHeader(o,e.headers[o]);y(n,"load",()=>{n.status===0||n.status>=200&&n.status<300||n.status===304?i(n):s(ft(Error(n.statusText),{xhr:n,status:n.status}))}),y(n,"error",()=>s(ft(Error("Network Error"),{xhr:n}))),y(n,"timeout",()=>s(ft(Error("Network Timeout"),{xhr:n}))),n.send(e.data)})}var Bl=Object.freeze({__proto__:null,Countdown:Rr,Filter:sa,Lightbox:Qa,LightboxPanel:no,Notification:il,Parallax:ul,Slider:gl,SliderParallax:Io,Slideshow:bl,SlideshowParallax:Io,Sortable:wl,Tooltip:El,Upload:Al});function Nl(t){Wt&&window.MutationObserver&&(document.body?requestAnimationFrame(()=>Ao(t)):new MutationObserver((e,i)=>{document.body&&(Ao(t),i.disconnect())}).observe(document.documentElement,{childList:!0}))}function Ao(t){v(document,"uikit:init",t),document.body&&_t(document.body,Oo),new MutationObserver(zl).observe(document,{subtree:!0,childList:!0,attributes:!0}),t._initialized=!0}function zl(t){var e;for(const{addedNodes:i,removedNodes:s,target:n,attributeName:o}of t){for(const a of i)_t(a,Oo);for(const a of s)_t(a,Fl);const r=o&&Do(o);r&&(Et(n,o)?Ye(r,n):(e=Ti(n,r))==null||e.$destroy())}}function Oo(t){const e=Ge(t);for(const i in e)_s(e[i]);for(const i of t.getAttributeNames()){const s=Do(i);s&&Ye(s,t)}}function Fl(t){const e=Ge(t);for(const i in e)As(e[i])}function Do(t){mt(t,"data-")&&(t=t.slice(5));const e=ve[t];return e&&(e.options||e).name}Ra(lt),qa(lt);var Mo={mixins:[it,Yt],props:{animation:Boolean,targets:String,active:null,collapsible:Boolean,multiple:Boolean,toggle:String,content:String,offset:Number},data:{targets:"> *",active:!1,animation:!0,collapsible:!0,multiple:!1,clsOpen:"uk-open",toggle:"> .uk-accordion-title",content:"> .uk-accordion-content",offset:0},computed:{items:({targets:t},e)=>D(t,e),toggles({toggle:t}){return this.items.map(e=>$(t,e))},contents({content:t}){return this.items.map(e=>{var i;return((i=e._wrapper)==null?void 0:i.firstElementChild)||$(t,e)})}},watch:{items(t,e){if(e||x(t,this.clsOpen))return;const i=this.active!==!1&&t[Number(this.active)]||!this.collapsible&&t[0];i&&this.toggle(i,!1)},toggles(){this.$emit()},contents(t){for(const e of t){const i=x(this.items.find(s=>s.contains(e)),this.clsOpen);Mi(e,!i)}this.$emit()}},observe:yi(),events:[{name:"click keydown",delegate:({targets:t,$props:e})=>`${t} ${e.toggle}`,async handler(t){var e;t.type==="keydown"&&t.keyCode!==M.SPACE||(t.preventDefault(),(e=this._off)==null||e.call(this),this._off=Ll(t.target),await this.toggle(yt(this.toggles,t.current)),this._off())}},{name:"shown hidden",self:!0,delegate:({targets:t})=>t,handler(){this.$emit()}}],update(){const t=Oe(this.items,`.${this.clsOpen}`);for(const e in this.items){const i=this.toggles[e],s=this.contents[e];if(!i||!s)continue;i.id=Jt(this,i),s.id=Jt(this,s);const n=b(t,this.items[e]);p(i,{role:z(i,"a")?"button":null,"aria-controls":s.id,"aria-expanded":n,"aria-disabled":!this.collapsible&&t.length<2&&n}),p(s,{role:"region","aria-labelledby":i.id}),z(s,"ul")&&p(B(s),"role","presentation")}},methods:{toggle(t,e){t=this.items[ot(t,this.items)];let i=[t];const s=Oe(this.items,`.${this.clsOpen}`);if(!this.multiple&&!b(s,i[0])&&(i=i.concat(s)),!(!this.collapsible&&s.length<2&&b(s,t)))return Promise.all(i.map(n=>this.toggleElement(n,!b(s,n),(o,r)=>{if(H(o,this.clsOpen,r),e===!1||!this.animation){Mi($(this.content,o),!r);return}return Hl(o,r,this)})))}}};function Mi(t,e){t&&(t.hidden=e)}async function Hl(t,e,{content:i,duration:s,velocity:n,transition:o}){var r;i=((r=t._wrapper)==null?void 0:r.firstElementChild)||$(i,t),t._wrapper||(t._wrapper=Ne(i,"<div>"));const a=t._wrapper;h(a,"overflow","hidden");const l=k(h(a,"height"));await N.cancel(a),Mi(i,!1);const c=Ht(["marginTop","marginBottom"],d=>h(i,d))+m(i).height,u=l/c;s=(n*c+s)*(e?1-u:u),h(a,"height",l),await N.start(a,{height:e?c:0},s,o),ze(i),delete t._wrapper,e||Mi(i,!0)}function Ll(t){const e=Ot(t,!0);let i;return function s(){i=requestAnimationFrame(()=>{const{top:n}=m(t);n<0&&(e.scrollTop+=n),s()})}(),()=>requestAnimationFrame(()=>cancelAnimationFrame(i))}var Wl={mixins:[it,Yt],args:"animation",props:{animation:Boolean,close:String},data:{animation:!0,selClose:".uk-alert-close",duration:150},events:{name:"click",delegate:({selClose:t})=>t,handler(t){t.preventDefault(),this.close()}},methods:{async close(){await this.toggleElement(this.$el,!1,jl),this.$destroy(!0)}}};function jl(t,e,{duration:i,transition:s,velocity:n}){const o=k(h(t,"height"));return h(t,"height",o),N.start(t,{height:0,marginTop:0,marginBottom:0,paddingTop:0,paddingBottom:0,borderTop:0,borderBottom:0,opacity:0},n*o+i,s)}var Bo={args:"autoplay",props:{automute:Boolean,autoplay:Boolean},data:{automute:!1,autoplay:!0},beforeConnect(){this.autoplay==="inview"&&!Et(this.$el,"preload")&&(this.$el.preload="none"),z(this.$el,"iframe")&&!Et(this.$el,"allow")&&(this.$el.allow="autoplay"),this.autoplay==="hover"&&(z(this.$el,"video")?this.$el.tabindex=0:this.autoplay=!0),this.automute&&cn(this.$el)},events:[{name:`${jt} focusin`,filter:({autoplay:t})=>b(t,"hover"),handler(t){!pt(t)||!Rl(this.$el)?rs(this.$el):bi(this.$el)}},{name:`${le} focusout`,filter:({autoplay:t})=>b(t,"hover"),handler(t){pt(t)||bi(this.$el)}}],observe:[ge({filter:({autoplay:t})=>t!=="hover",handler([{isIntersecting:t}]){document.fullscreenElement||(t?this.autoplay&&rs(this.$el):bi(this.$el))},args:{intersecting:!1},options:({$el:t,autoplay:e})=>({root:e==="inview"?null:O(t).closest(":not(a)")})})]};function Rl(t){return!t.paused&&!t.ended}var ql={mixins:[Bo],props:{width:Number,height:Number},data:{automute:!0},created(){this.useObjectFit=z(this.$el,"img","video")},observe:dt({target:({$el:t})=>No(t)||O(t),filter:({useObjectFit:t})=>!t}),update:{read(){if(this.useObjectFit)return!1;const{ratio:t,cover:e}=Ri,{$el:i,width:s,height:n}=this;let o={width:s,height:n};if(!s||!n){const c={width:i.naturalWidth||i.videoWidth||i.clientWidth,height:i.naturalHeight||i.videoHeight||i.clientHeight};s?o=t(c,"width",s):n?o=t(c,"height",n):o=c}const{offsetHeight:r,offsetWidth:a}=No(i)||O(i),l=e(o,{width:a,height:r});return!l.width||!l.height?!1:l},write({height:t,width:e}){h(this.$el,{height:t,width:e})},events:["resize"]}};function No(t){for(;t=O(t);)if(h(t,"position")!=="static")return t}let Y;var zo={mixins:[Ue,Fn,Yt],args:"pos",props:{mode:"list",toggle:Boolean,boundary:Boolean,boundaryX:Boolean,boundaryY:Boolean,target:Boolean,targetX:Boolean,targetY:Boolean,stretch:Boolean,delayShow:Number,delayHide:Number,autoUpdate:Boolean,clsDrop:String,animateOut:Boolean,bgScroll:Boolean,closeOnScroll:Boolean},data:{mode:["click","hover"],toggle:"- *",boundary:!1,boundaryX:!1,boundaryY:!1,target:!1,targetX:!1,targetY:!1,stretch:!1,delayShow:0,delayHide:800,autoUpdate:!0,clsDrop:!1,animateOut:!1,bgScroll:!0,animation:["uk-animation-fade"],cls:"uk-open",container:!1,closeOnScroll:!1},computed:{boundary({boundary:t,boundaryX:e,boundaryY:i},s){return[tt(e||t,s)||window,tt(i||t,s)||window]},target({target:t,targetX:e,targetY:i},s){return e||(e=t||this.targetEl),i||(i=t||this.targetEl),[e===!0?window:tt(e,s),i===!0?window:tt(i,s)]}},created(){this.tracker=new an},beforeConnect(){this.clsDrop=this.$props.clsDrop||this.$options.id},connected(){S(this.$el,"uk-drop",this.clsDrop),this.toggle&&!this.targetEl&&(this.targetEl=Vl(this)),this._style=ei(this.$el.style,["width","height"])},disconnected(){this.isActive()&&(this.hide(!1),Y=null),h(this.$el,this._style)},events:[{name:"click",delegate:()=>".uk-drop-close",handler(t){t.preventDefault(),this.hide(!1)}},{name:"click",delegate:()=>'a[href*="#"]',handler({defaultPrevented:t,current:e}){const{hash:i}=e;!t&&i&&ce(e)&&!this.$el.contains($(i))&&this.hide(!1)}},{name:"beforescroll",handler(){this.hide(!1)}},{name:"toggle",self:!0,handler(t,e){t.preventDefault(),this.isToggled()?this.hide(!1):this.show(e==null?void 0:e.$el,!1)}},{name:"toggleshow",self:!0,handler(t,e){t.preventDefault(),this.show(e==null?void 0:e.$el)}},{name:"togglehide",self:!0,handler(t){t.preventDefault(),C(this.$el,":focus,:hover")||this.hide()}},{name:`${jt} focusin`,filter:({mode:t})=>b(t,"hover"),handler(t){pt(t)||this.clearTimers()}},{name:`${le} focusout`,filter:({mode:t})=>b(t,"hover"),handler(t){!pt(t)&&t.relatedTarget&&this.hide()}},{name:"toggled",self:!0,handler(t,e){e&&(this.clearTimers(),this.position())}},{name:"show",self:!0,handler(){Y=this,this.tracker.init(),p(this.targetEl,"aria-expanded",!0);const t=[Yl(this),Gl(this),Jl(this),this.autoUpdate&&Fo(this),this.closeOnScroll&&Xl(this)];L(this.$el,"hide",()=>t.forEach(e=>e&&e()),{self:!0}),this.bgScroll||L(this.$el,"hidden",zn(this.$el),{self:!0})}},{name:"beforehide",self:!0,handler(){this.clearTimers()}},{name:"hide",handler({target:t}){if(this.$el!==t){Y=Y===null&&this.$el.contains(t)&&this.isToggled()?this:Y;return}Y=this.isActive()?null:Y,this.tracker.cancel(),p(this.targetEl,"aria-expanded",null)}}],update:{write(){this.isToggled()&&!x(this.$el,this.clsEnter)&&this.position()}},methods:{show(t=this.targetEl,e=!0){if(this.isToggled()&&t&&this.targetEl&&t!==this.targetEl&&this.hide(!1,!1),this.targetEl=t,this.clearTimers(),!this.isActive()){if(Y){if(e&&Y.isDelaying()){this.showTimer=setTimeout(()=>C(t,":hover")&&this.show(),10);return}let i;for(;Y&&i!==Y&&!Y.$el.contains(this.$el);)i=Y,Y.hide(!1,!1)}this.container&&O(this.$el)!==this.container&&W(this.container,this.$el),this.showTimer=setTimeout(()=>this.toggleElement(this.$el,!0),e&&this.delayShow||0)}},hide(t=!0,e=!0){const i=()=>this.toggleElement(this.$el,!1,this.animateOut&&e);this.clearTimers(),this.isDelayedHide=t,t&&this.isDelaying()?this.hideTimer=setTimeout(this.hide,50):t&&this.delayHide?this.hideTimer=setTimeout(i,this.delayHide):i()},clearTimers(){clearTimeout(this.showTimer),clearTimeout(this.hideTimer),this.showTimer=null,this.hideTimer=null},isActive(){return Y===this},isDelaying(){return[this.$el,...D(".uk-drop",this.$el)].some(t=>this.tracker.movesTo(t))},position(){const t=Ts(this.$el);_(this.$el,"uk-drop-stack"),h(this.$el,this._style),this.$el.hidden=!0;const e=this.target.map(o=>Ul(this.$el,o)),i=this.getViewportOffset(this.$el),s=[[0,["x","width","left","right"]],[1,["y","height","top","bottom"]]];for(const[o,[r,a]]of s)this.axis!==r&&b([r,!0],this.stretch)&&h(this.$el,{[a]:Math.min(E(this.boundary[o])[a],e[o][a]-2*i),[`overflow-${r}`]:"auto"});const n=e[0].width-2*i;this.$el.hidden=!1,h(this.$el,"maxWidth",""),this.$el.offsetWidth>n&&S(this.$el,"uk-drop-stack"),h(this.$el,"maxWidth",n),this.positionAt(this.$el,this.target,this.boundary);for(const[o,[r,a,l,c]]of s)if(this.axis===r&&b([r,!0],this.stretch)){const u=Math.abs(this.getPositionOffset()),d=E(this.target[o]),f=E(this.$el);h(this.$el,{[a]:(d[l]>f[l]?d[this.inset?c:l]-Math.max(E(this.boundary[o])[l],e[o][l]+i):Math.min(E(this.boundary[o])[c],e[o][c]-i)-d[this.inset?l:c])-u,[`overflow-${r}`]:"auto"}),this.positionAt(this.$el,this.target,this.boundary)}t()}}};function Ul(t,e){return rt(Vt(e).find(i=>i.contains(t)))}function Vl(t){const{$el:e}=t.$create("toggle",tt(t.toggle,t.$el),{target:t.$el,mode:t.mode});return p(e,"aria-haspopup",!0),e}function Yl(t){const e=()=>t.$emit(),i=[ns(e),Le(Vt(t.$el).concat(t.target),e)];return()=>i.map(s=>s.disconnect())}function Fo(t,e=()=>t.$emit()){return y([document,...Vt(t.$el)],"scroll",e,{passive:!0})}function Gl(t){return y(document,"keydown",e=>{e.keyCode===M.ESC&&t.hide(!1)})}function Xl(t){return Fo(t,()=>t.hide(!1))}function Jl(t){return y(document,ut,({target:e})=>{t.$el.contains(e)||L(document,`${Ct} ${ri} scroll`,({defaultPrevented:i,type:s,target:n})=>{var o;!i&&s===Ct&&e===n&&!((o=t.targetEl)!=null&&o.contains(e))&&t.hide(!1)},!0)})}var Ho={mixins:[it,Ue],props:{align:String,clsDrop:String,boundary:Boolean,dropbar:Boolean,dropbarAnchor:Boolean,duration:Number,mode:Boolean,offset:Boolean,stretch:Boolean,delayShow:Boolean,delayHide:Boolean,target:Boolean,targetX:Boolean,targetY:Boolean,animation:Boolean,animateOut:Boolean,closeOnScroll:Boolean},data:{align:U?"right":"left",clsDrop:"uk-dropdown",clsDropbar:"uk-dropnav-dropbar",boundary:!0,dropbar:!1,dropbarAnchor:!1,duration:200,container:!1,selNavItem:"> li > a, > ul > li > a"},computed:{dropbarAnchor:({dropbarAnchor:t},e)=>tt(t,e)||e,dropbar({dropbar:t}){return t?(t=this._dropbar||tt(t,this.$el)||$(`+ .${this.clsDropbar}`,this.$el),t||(this._dropbar=$("<div></div>"))):null},dropContainer(t,e){return this.container||e},dropdowns({clsDrop:t},e){var i;const s=D(`.${t}`,e);if(this.dropContainer!==e)for(const n of D(`.${t}`,this.dropContainer)){const o=(i=this.getDropdown(n))==null?void 0:i.targetEl;!b(s,n)&&o&&this.$el.contains(o)&&s.push(n)}return s},items({selNavItem:t},e){return D(t,e)}},watch:{dropbar(t){S(t,"uk-dropbar","uk-dropbar-top",this.clsDropbar,`uk-${this.$options.name}-dropbar`)},dropdowns(){this.initializeDropdowns()}},connected(){this.initializeDropdowns()},disconnected(){Q(this._dropbar),delete this._dropbar},events:[{name:"mouseover focusin",delegate:({selNavItem:t})=>t,handler({current:t}){const e=this.getActive();e&&b(e.mode,"hover")&&e.targetEl&&!t.contains(e.targetEl)&&!e.isDelaying()&&e.hide(!1)}},{name:"keydown",self:!0,delegate:({selNavItem:t})=>t,handler(t){var e;const{current:i,keyCode:s}=t,n=this.getActive();s===M.DOWN&&(n==null?void 0:n.targetEl)===i&&(t.preventDefault(),(e=$(Ae,n.$el))==null||e.focus()),Lo(t,this.items,n)}},{name:"keydown",el:({dropContainer:t})=>t,delegate:({clsDrop:t})=>`.${t}`,handler(t){var e;const{current:i,keyCode:s,target:n}=t;if(ai(n)||!b(this.dropdowns,i))return;const o=this.getActive();let r=-1;if(s===M.HOME?r=0:s===M.END?r="last":s===M.UP?r="previous":s===M.DOWN?r="next":s===M.ESC&&((e=o.targetEl)==null||e.focus()),~r){t.preventDefault();const a=D(Ae,i);a[ot(r,a,xt(a,l=>C(l,":focus")))].focus()}Lo(t,this.items,o)}},{name:"mouseleave",el:({dropbar:t})=>t,filter:({dropbar:t})=>t,handler(){const t=this.getActive();t&&b(t.mode,"hover")&&!this.dropdowns.some(e=>C(e,":hover"))&&t.hide()}},{name:"beforeshow",el:({dropContainer:t})=>t,filter:({dropbar:t})=>t,handler({target:t}){this.isDropbarDrop(t)&&(this.dropbar.previousElementSibling!==this.dropbarAnchor&&di(this.dropbarAnchor,this.dropbar),S(t,`${this.clsDrop}-dropbar`))}},{name:"show",el:({dropContainer:t})=>t,filter:({dropbar:t})=>t,handler({target:t}){if(!this.isDropbarDrop(t))return;const e=this.getDropdown(t),i=()=>{const s=Math.max(...he(t,`.${this.clsDrop}`).concat(t).map(n=>E(n).bottom));E(this.dropbar,{left:E(this.dropbar).left,top:this.getDropbarOffset(e.getPositionOffset())}),this.transitionTo(s-E(this.dropbar).top+k(h(t,"marginBottom")),t)};this._observer=Le([e.$el,...e.target],i),i()}},{name:"beforehide",el:({dropContainer:t})=>t,filter:({dropbar:t})=>t,handler(t){const e=this.getActive();C(this.dropbar,":hover")&&e.$el===t.target&&this.isDropbarDrop(e.$el)&&b(e.mode,"hover")&&e.isDelayedHide&&!this.items.some(i=>e.targetEl!==i&&C(i,":focus"))&&t.preventDefault()}},{name:"hide",el:({dropContainer:t})=>t,filter:({dropbar:t})=>t,handler({target:t}){var e;if(!this.isDropbarDrop(t))return;(e=this._observer)==null||e.disconnect();const i=this.getActive();(!i||i.$el===t)&&this.transitionTo(0)}}],methods:{getActive(){var t;return b(this.dropdowns,(t=Y)==null?void 0:t.$el)&&Y},async transitionTo(t,e){const{dropbar:i}=this,s=et(i);if(e=s<t&&e,await N.cancel([e,i]),e){const n=E(e).top-E(i).top-s;n>0&&h(e,"transitionDelay",`${n/t*this.duration}ms`)}h(e,"clipPath",`polygon(0 0,100% 0,100% ${s}px,0 ${s}px)`),et(i,s),await Promise.all([N.start(i,{height:t},this.duration),N.start(e,{clipPath:`polygon(0 0,100% 0,100% ${t}px,0 ${t}px)`},this.duration).finally(()=>h(e,{clipPath:"",transitionDelay:""}))]).catch(A)},getDropdown(t){return this.$getComponent(t,"drop")||this.$getComponent(t,"dropdown")},isDropbarDrop(t){return b(this.dropdowns,t)&&x(t,this.clsDrop)},getDropbarOffset(t){const{$el:e,target:i,targetY:s}=this,{top:n,height:o}=E(tt(s||i||e,e));return n+o+t},initializeDropdowns(){this.$create("drop",this.dropdowns.filter(t=>!this.getDropdown(t)),{...this.$props,flip:!1,shift:!0,pos:`bottom-${this.align}`,boundary:this.boundary===!0?this.$el:this.boundary})}}};function Lo(t,e,i){var s,n,o;const{current:r,keyCode:a}=t;let l=-1;a===M.HOME?l=0:a===M.END?l="last":a===M.LEFT?l="previous":a===M.RIGHT?l="next":a===M.TAB&&((s=i.targetEl)==null||s.focus(),(n=i.hide)==null||n.call(i,!1)),~l&&(t.preventDefault(),(o=i.hide)==null||o.call(i,!1),e[ot(l,e,e.indexOf(i.targetEl||r))].focus())}var Kl={mixins:[it],args:"target",props:{target:Boolean},data:{target:!1},computed:{input:(t,e)=>$(_e,e),state(){return this.input.nextElementSibling},target({target:t},e){return t&&(t===!0&&O(this.input)===e&&this.input.nextElementSibling||$(t,e))}},update(){var t;const{target:e,input:i}=this;if(!e)return;let s;const n=ai(e)?"value":"textContent",o=e[n],r=(t=i.files)!=null&&t[0]?i.files[0].name:C(i,"select")&&(s=D("option",i).filter(a=>a.selected)[0])?s.textContent:i.value;o!==r&&(e[n]=r)},events:[{name:"change",handler(){this.$emit()}},{name:"reset",el:({$el:t})=>t.closest("form"),handler(){this.$emit()}}]},Zl={extends:Tn,mixins:[it],name:"grid",props:{masonry:Boolean,parallax:String,parallaxStart:String,parallaxEnd:String,parallaxJustify:Boolean},data:{margin:"uk-grid-margin",clsStack:"uk-grid-stack",masonry:!1,parallax:0,parallaxStart:0,parallaxEnd:0,parallaxJustify:!1},connected(){this.masonry&&S(this.$el,"uk-flex-top","uk-flex-wrap-top")},observe:Re({filter:({parallax:t,parallaxJustify:e})=>t||e}),update:[{write({rows:t}){H(this.$el,this.clsStack,!t.some(e=>e.length>1))},events:["resize"]},{read(t){const{rows:e}=t;let{masonry:i,parallax:s,parallaxJustify:n,margin:o}=this;if(s=Math.max(0,G(s)),!(i||s||n)||Wo(e)||e[0].some((w,I)=>e.some(P=>P[I]&&P[I].offsetWidth!==w.offsetWidth)))return t.translates=t.scrollColumns=!1;let r=th(e,o),a,l;i?[a,l]=Ql(e,r,i==="next"):a=eh(e);const c=a.map(w=>Ht(w,"offsetHeight")+r*(w.length-1)),u=Math.max(0,...c);let d,f,g;return(s||n)&&(d=c.map((w,I)=>n?u-w+s:s/(I%2||8)),n||(s=Math.max(...c.map((w,I)=>w+d[I]-u))),f=G(this.parallaxStart,"height",this.$el,!0),g=G(this.parallaxEnd,"height",this.$el,!0)),{columns:a,translates:l,scrollColumns:d,parallaxStart:f,parallaxEnd:g,padding:s,height:l?u:""}},write({height:t,padding:e}){h(this.$el,"paddingBottom",e||""),t!==!1&&h(this.$el,"height",t)},events:["resize"]},{read({rows:t,scrollColumns:e,parallaxStart:i,parallaxEnd:s}){return{scrolled:e&&!Wo(t)?wi(this.$el,i,s):!1}},write({columns:t,scrolled:e,scrollColumns:i,translates:s}){!e&&!s||t.forEach((n,o)=>n.forEach((r,a)=>{let[l,c]=s&&s[o][a]||[0,0];e&&(c+=e*i[o]),h(r,"transform",`translate(${l}px, ${c}px)`)}))},events:["scroll","resize"]}]};function Wo(t){return t.flat().some(e=>h(e,"position")==="absolute")}function Ql(t,e,i){const s=[],n=[],o=Array(t[0].length).fill(0);let r=0;for(let a of t){U&&a.reverse();let l=0;for(const c in a){const{offsetWidth:u,offsetHeight:d}=a[c],f=i?c:o.indexOf(Math.min(...o));Ms(s,f,a[c]),Ms(n,f,[(f-c)*u*(U?-1:1),o[f]-r]),o[f]+=d+e,l=Math.max(l,d)}r+=l+e}return[s,n]}function th(t,e){const i=t.flat().find(s=>x(s,e));return k(i?h(i,"marginTop"):h(t[0][0],"paddingLeft"))}function eh(t){const e=[];for(const i of t)for(const s in i)Ms(e,s,i[s]);return e}function Ms(t,e,i){t[e]||(t[e]=[]),t[e].push(i)}var ih={args:"target",props:{target:String,row:Boolean},data:{target:"> *",row:!0},computed:{elements:({target:t},e)=>D(t,e)},observe:dt({target:({$el:t,elements:e})=>e.reduce((i,s)=>i.concat(s,...s.children),[t])}),events:{name:"loadingdone",el:()=>document.fonts,handler(){this.$emit("resize")}},update:{read(){return{rows:(this.row?bs(this.elements):[this.elements]).map(sh)}},write({rows:t}){for(const{heights:e,elements:i}of t)i.forEach((s,n)=>h(s,"minHeight",e[n]))},events:["resize"]}};function sh(t){if(t.length<2)return{heights:[""],elements:t};let e=t.map(nh);const i=Math.max(...e);return{heights:t.map((s,n)=>e[n].toFixed(2)===i.toFixed(2)?"":i),elements:t}}function nh(t){const e=ei(t.style,["display","minHeight"]);q(t)||h(t,"display","block","important"),h(t,"minHeight","");const i=m(t).height-de(t,"height","content-box");return h(t,e),i}var oh={args:"target",props:{target:String},data:{target:""},computed:{target:{get:({target:t},e)=>tt(t,e),observe:({target:t})=>t}},observe:dt({target:({target:t})=>t}),update:{read(){return this.target?{height:this.target.offsetHeight}:!1},write({height:t}){h(this.$el,"minHeight",t)},events:["resize"]}},rh={props:{expand:Boolean,offsetTop:Boolean,offsetBottom:Boolean,minHeight:Number},data:{expand:!1,offsetTop:!1,offsetBottom:!1,minHeight:0},observe:[vs({filter:({expand:t})=>t}),dt({target:({$el:t})=>Ut(t)})],update:{read(){if(!q(this.$el))return!1;let t="";const e=de(this.$el,"height","content-box"),{body:i,scrollingElement:s}=document,n=Ot(this.$el),{height:o}=rt(n===i?s:n),r=s===n||i===n;if(t=`calc(${r?"100vh":`${o}px`}`,this.expand){const a=m(n).height-m(this.$el).height;t+=` - ${a}px`}else{if(this.offsetTop)if(r){const a=this.offsetTop===!0?this.$el:tt(this.offsetTop,this.$el),{top:l}=E(a);t+=l>0&&l<o/2?` - ${l}px`:""}else t+=` - ${de(n,"height",h(n,"boxSizing"))}px`;this.offsetBottom===!0?t+=` - ${m(this.$el.nextElementSibling).height}px`:vt(this.offsetBottom)?t+=` - ${this.offsetBottom}vh`:this.offsetBottom&&ee(this.offsetBottom,"px")?t+=` - ${k(this.offsetBottom)}px`:F(this.offsetBottom)&&(t+=` - ${m(tt(this.offsetBottom,this.$el)).height}px`)}return t+=`${e?` - ${e}px`:""})`,{minHeight:t}},write({minHeight:t}){h(this.$el,"minHeight",`max(${this.minHeight||0}px, ${t})`)},events:["resize"]}},ah='<svg width="14" height="14" viewBox="0 0 14 14"><line fill="none" stroke="#000" stroke-width="1.1" x1="1" y1="1" x2="13" y2="13"/><line fill="none" stroke="#000" stroke-width="1.1" x1="13" y1="1" x2="1" y2="13"/></svg>',lh='<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" stroke-width="1.4" x1="1" y1="1" x2="19" y2="19"/><line fill="none" stroke="#000" stroke-width="1.4" x1="19" y1="1" x2="1" y2="19"/></svg>',hh='<svg width="12" height="12" viewBox="0 0 12 12"><polyline fill="none" stroke="#000" stroke-width="1.1" points="1 3.5 6 8.5 11 3.5"/></svg>',ch='<svg width="20" height="20" viewBox="0 0 20 20"><rect width="1" height="11" x="9" y="4"/><rect width="11" height="1" x="4" y="9"/></svg>',uh='<svg width="14" height="14" viewBox="0 0 14 14"><polyline fill="none" stroke="#000" stroke-width="1.1" points="1 4 7 10 13 4"/></svg>',dh='<svg width="12" height="12" viewBox="0 0 12 12"><polyline fill="none" stroke="#000" stroke-width="1.1" points="1 3.5 6 8.5 11 3.5"/></svg>',fh='<svg width="12" height="12" viewBox="0 0 12 12"><polyline fill="none" stroke="#000" stroke-width="1.1" points="1 3.5 6 8.5 11 3.5"/></svg>',ph='<svg width="20" height="20" viewBox="0 0 20 20"><style>.uk-navbar-toggle-icon svg&gt;[class*=&quot;line-&quot;]{transition:0.2s ease-in-out;transition-property:transform, opacity;transform-origin:center;opacity:1}.uk-navbar-toggle-icon svg&gt;.line-3{opacity:0}.uk-navbar-toggle-animate[aria-expanded=&quot;true&quot;] svg&gt;.line-3{opacity:1}.uk-navbar-toggle-animate[aria-expanded=&quot;true&quot;] svg&gt;.line-2{transform:rotate(45deg)}.uk-navbar-toggle-animate[aria-expanded=&quot;true&quot;] svg&gt;.line-3{transform:rotate(-45deg)}.uk-navbar-toggle-animate[aria-expanded=&quot;true&quot;] svg&gt;.line-1,.uk-navbar-toggle-animate[aria-expanded=&quot;true&quot;] svg&gt;.line-4{opacity:0}.uk-navbar-toggle-animate[aria-expanded=&quot;true&quot;] svg&gt;.line-1{transform:translateY(6px) scaleX(0)}.uk-navbar-toggle-animate[aria-expanded=&quot;true&quot;] svg&gt;.line-4{transform:translateY(-6px) scaleX(0)}</style><rect width="20" height="2" y="3" class="line-1"/><rect width="20" height="2" y="9" class="line-2"/><rect width="20" height="2" y="9" class="line-3"/><rect width="20" height="2" y="15" class="line-4"/></svg>',gh='<svg width="40" height="40" viewBox="0 0 40 40"><rect width="1" height="40" x="19" y="0"/><rect width="40" height="1" x="0" y="19"/></svg>',mh='<svg width="7" height="12" viewBox="0 0 7 12"><polyline fill="none" stroke="#000" stroke-width="1.2" points="1 1 6 6 1 11"/></svg>',vh='<svg width="7" height="12" viewBox="0 0 7 12"><polyline fill="none" stroke="#000" stroke-width="1.2" points="6 1 1 6 6 11"/></svg>',jo='<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="9" cy="9" r="7"/><path fill="none" stroke="#000" stroke-width="1.1" d="M14,14 L18,18 L14,14 Z"/></svg>',bh='<svg width="40" height="40" viewBox="0 0 40 40"><circle fill="none" stroke="#000" stroke-width="1.8" cx="17.5" cy="17.5" r="16.5"/><line fill="none" stroke="#000" stroke-width="1.8" x1="38" y1="39" x2="29" y2="30"/></svg>',wh='<svg width="24" height="24" viewBox="0 0 24 24"><circle fill="none" stroke="#000" stroke-width="1.1" cx="10.5" cy="10.5" r="9.5"/><line fill="none" stroke="#000" stroke-width="1.1" x1="23" y1="23" x2="17" y2="17"/></svg>',xh='<svg width="25" height="40" viewBox="0 0 25 40"><polyline fill="none" stroke="#000" stroke-width="2" points="4.002,38.547 22.527,20.024 4,1.5"/></svg>',$h='<svg width="14" height="24" viewBox="0 0 14 24"><polyline fill="none" stroke="#000" stroke-width="1.4" points="1.225,23 12.775,12 1.225,1"/></svg>',yh='<svg width="25" height="40" viewBox="0 0 25 40"><polyline fill="none" stroke="#000" stroke-width="2" points="20.527,1.5 2,20.024 20.525,38.547"/></svg>',kh='<svg width="14" height="24" viewBox="0 0 14 24"><polyline fill="none" stroke="#000" stroke-width="1.4" points="12.775,1 1.225,12 12.775,23"/></svg>',Sh='<svg width="30" height="30" viewBox="0 0 30 30"><circle fill="none" stroke="#000" cx="15" cy="15" r="14"/></svg>',Ih='<svg width="18" height="10" viewBox="0 0 18 10"><polyline fill="none" stroke="#000" stroke-width="1.2" points="1 9 9 1 17 9"/></svg>',Ro={args:"src",props:{width:Number,height:Number,ratio:Number},data:{ratio:1},connected(){this.svg=this.getSvg().then(t=>{if(!this._connected)return;const e=Th(t,this.$el);return this.svgEl&&e!==this.svgEl&&Q(this.svgEl),Eh.call(this,e,t),this.svgEl=e},A)},disconnected(){this.svg.then(t=>{this._connected||(qi(this.$el)&&(this.$el.hidden=!1),Q(t),this.svgEl=null)}),this.svg=null},methods:{async getSvg(){}}};function Th(t,e){if(qi(e)||z(e,"canvas")){e.hidden=!0;const s=e.nextElementSibling;return qo(t,s)?s:di(e,t)}const i=e.lastElementChild;return qo(t,i)?i:W(e,t)}function qo(t,e){return z(t,"svg")&&z(e,"svg")&&t.innerHTML===e.innerHTML}function Eh(t,e){const i=["width","height"];let s=i.map(o=>this[o]);s.some(o=>o)||(s=i.map(o=>p(e,o)));const n=p(e,"viewBox");n&&!s.some(o=>o)&&(s=n.split(" ").slice(2)),s.forEach((o,r)=>p(t,i[r],k(o)*this.ratio||null))}function Uo(t,e){return e&&b(t,"<symbol")&&(t=Ch(t)[e]||t),T(St(t)).filter(se)[0]}const Vo=/<symbol([^]*?id=(['"])(.+?)\2[^]*?<\/)symbol>/g,Ch=ct(function(t){const e={};Vo.lastIndex=0;let i;for(;i=Vo.exec(t);)e[i[3]]=`<svg ${i[1]}svg>`;return e}),Bi={spinner:Sh,totop:Ih,marker:ch,"close-icon":ah,"close-large":lh,"drop-parent-icon":hh,"nav-parent-icon":dh,"nav-parent-icon-large":uh,"navbar-parent-icon":fh,"navbar-toggle-icon":ph,"overlay-icon":gh,"pagination-next":mh,"pagination-previous":vh,"search-icon":jo,"search-medium":wh,"search-large":bh,"search-toggle-icon":jo,"slidenav-next":$h,"slidenav-next-large":xh,"slidenav-previous":kh,"slidenav-previous-large":yh},Bs={install:Fh,mixins:[Ro],args:"icon",props:{icon:String},isIcon:!0,beforeConnect(){S(this.$el,"uk-icon")},methods:{async getSvg(){const t=Lh(this.icon);if(!t)throw"Icon not found.";return t}}},Zt={args:!1,extends:Bs,data:t=>({icon:Bt(t.constructor.options.name)}),beforeConnect(){S(this.$el,this.$options.id)}},Ph={extends:Zt,beforeConnect(){const t=this.$props.icon;this.icon=this.$el.closest(".uk-nav-primary")?`${t}-large`:t}},_h={extends:Zt,mixins:[Si],i18n:{toggle:"Open Search",submit:"Submit Search"},beforeConnect(){const t=x(this.$el,"uk-search-toggle")||x(this.$el,"uk-navbar-toggle");if(this.icon=t?"search-toggle-icon":x(this.$el,"uk-search-icon")&&this.$el.closest(".uk-search-large")?"search-large":this.$el.closest(".uk-search-medium")?"search-medium":this.$props.icon,!Et(this.$el,"aria-label"))if(t){const e=this.t("toggle");p(this.$el,"aria-label",e)}else{const e=this.$el.closest("a,button");if(e){const i=this.t("submit");p(e,"aria-label",i)}}}},Ah={extends:Zt,beforeConnect(){p(this.$el,"role","status")},methods:{async getSvg(){const t=await Bs.methods.getSvg.call(this);return this.ratio!==1&&h($("circle",t),"strokeWidth",1/this.ratio),t}}},Qt={extends:Zt,mixins:[Si],beforeConnect(){const t=this.$el.closest("a,button");p(t,"role",this.role!==null&&z(t,"a")?"button":this.role);const e=this.t("label");e&&!Et(t,"aria-label")&&p(t,"aria-label",e)}},Yo={extends:Qt,beforeConnect(){S(this.$el,"uk-slidenav");const t=this.$props.icon;this.icon=x(this.$el,"uk-slidenav-large")?`${t}-large`:t}},Oh={extends:Qt,i18n:{label:"Open menu"}},Dh={extends:Qt,i18n:{label:"Close"},beforeConnect(){this.icon=`close-${x(this.$el,"uk-close-large")?"large":"icon"}`}},Mh={extends:Qt,i18n:{label:"Open"}},Bh={extends:Qt,i18n:{label:"Back to top"}},Nh={extends:Qt,i18n:{label:"Next page"},data:{role:null}},zh={extends:Qt,i18n:{label:"Previous page"},data:{role:null}},Ni={};function Fh(t){t.icon.add=(e,i)=>{const s=F(e)?{[e]:i}:e;oe(s,(n,o)=>{Bi[o]=n,delete Ni[o]}),t._initialized&&_t(document.body,n=>oe(t.getComponents(n),o=>{o.$options.isIcon&&o.icon in s&&o.$reset()}))}}const Hh={twitter:"x"};function Lh(t){return t=Hh[t]||t,Bi[t]?(Ni[t]||(Ni[t]=Uo(Bi[Wh(t)]||Bi[t])),Ni[t].cloneNode(!0)):null}function Wh(t){return U?Wi(Wi(t,"left","right"),"previous","next"):t}var jh={props:{target:String,selActive:String},data:{target:!1,selActive:!1},computed:{target:({target:t},e)=>t?D(t,e):e},observe:[ge({handler(t){this.isIntersecting=t.some(({isIntersecting:e})=>e),this.$emit()},target:({target:t})=>t,args:{intersecting:!1}}),$i({target:({target:t})=>t,options:{attributes:!0,attributeFilter:["class"],attributeOldValue:!0}}),{target:({target:t})=>t,observe:(t,e)=>{const i=Le([...T(t),document.documentElement],e),s=[y(document,"scroll itemshown itemhidden",e,{passive:!0,capture:!0}),y(document,"show hide transitionstart",n=>(e(),i.observe(n.target))),y(document,"shown hidden transitionend transitioncancel",n=>(e(),i.unobserve(n.target)))];return{observe:i.observe.bind(i),unobserve:i.unobserve.bind(i),disconnect(){i.disconnect(),s.map(n=>n())}}},handler(){this.$emit()}}],update:{read(){if(!this.isIntersecting)return!1;for(const t of T(this.target)){let e=!this.selActive||C(t,this.selActive)?Rh(t):"";e!==!1&&ni(t,"uk-light uk-dark",e)}}}};function Rh(t){const e=m(t),i=m(window);if(!ii(e,i))return!1;const{left:s,top:n,height:o,width:r}=e;let a;for(const l of[.25,.5,.75]){const c=t.ownerDocument.elementsFromPoint(Math.max(0,Math.min(s+r*l,i.width-1)),Math.max(0,Math.min(n+o/2,i.height-1)));for(const u of c){if(t.contains(u)||!qh(u)||u.closest('[class*="-leave"]')&&c.some(f=>u!==f&&C(f,'[class*="-enter"]')))continue;const d=h(u,"--uk-inverse");if(d){if(d===a)return`uk-${d}`;a=d;break}}}return a?`uk-${a}`:""}function qh(t){if(h(t,"visibility")!=="visible")return!1;for(;t;){if(h(t,"opacity")==="0")return!1;t=O(t)}return!0}var Uh={mixins:[it,Ei],props:{fill:String},data:{fill:"",clsWrapper:"uk-leader-fill",clsHide:"uk-leader-hide",attrFill:"data-fill"},computed:{fill:({fill:t},e)=>t||h(e,"--uk-leader-fill-content")},connected(){[this.wrapper]=ts(this.$el,`<span class="${this.clsWrapper}">`)},disconnected(){ze(this.wrapper.childNodes)},observe:dt(),update:{read(){return{width:Math.trunc(this.$el.offsetWidth/2),fill:this.fill,hide:!this.matchMedia}},write({width:t,fill:e,hide:i}){H(this.wrapper,this.clsHide,i),p(this.wrapper,this.attrFill,new Array(t).join(e))},events:["resize"]}},Vh={install:Yh,mixins:[Es],data:{clsPage:"uk-modal-page",selPanel:".uk-modal-dialog",selClose:'[class*="uk-modal-close"]'},events:[{name:"fullscreenchange webkitendfullscreen",capture:!0,handler(t){z(t.target,"video")&&this.isToggled()&&!document.fullscreenElement&&this.hide()}},{name:"show",self:!0,handler(){x(this.panel,"uk-margin-auto-vertical")?S(this.$el,"uk-flex"):h(this.$el,"display","block"),et(this.$el)}},{name:"hidden",self:!0,handler(){h(this.$el,"display",""),_(this.$el,"uk-flex")}}]};function Yh({modal:t}){t.dialog=function(i,s){const n=t($(`<div><div class="uk-modal-dialog">${i}</div></div>`),{stack:!0,role:"alertdialog",...s});return n.show(),y(n.$el,"hidden",async()=>{await Promise.resolve(),n.$destroy(!0)},{self:!0}),n},t.alert=function(i,s){return e(({i18n:n})=>`<div class="uk-modal-body">${F(i)?i:bt(i)}</div> <div class="uk-modal-footer uk-text-right"> <button class="uk-button uk-button-primary uk-modal-close" autofocus>${n.ok}</button> </div>`,s)},t.confirm=function(i,s){return e(({i18n:n})=>`<form> <div class="uk-modal-body">${F(i)?i:bt(i)}</div> <div class="uk-modal-footer uk-text-right"> <button class="uk-button uk-button-default uk-modal-close" type="button">${n.cancel}</button> <button class="uk-button uk-button-primary" autofocus>${n.ok}</button> </div> </form>`,s,()=>Promise.reject())},t.prompt=function(i,s,n){const o=e(({i18n:l})=>`<form class="uk-form-stacked"> <div class="uk-modal-body"> <label>${F(i)?i:bt(i)}</label> <input class="uk-input" autofocus> </div> <div class="uk-modal-footer uk-text-right"> <button class="uk-button uk-button-default uk-modal-close" type="button">${l.cancel}</button> <button class="uk-button uk-button-primary">${l.ok}</button> </div> </form>`,n,()=>null,()=>a.value),{$el:r}=o.dialog,a=$("input",r);return a.value=s||"",y(r,"show",()=>a.select()),o},t.i18n={ok:"Ok",cancel:"Cancel"};function e(i,s,n=A,o=A){s={bgClose:!1,escClose:!0,...s,i18n:{...t.i18n,...s==null?void 0:s.i18n}};const r=t.dialog(i(s),s);return ft(new Promise(a=>{const l=y(r.$el,"hide",()=>a(n()));y(r.$el,"submit","form",c=>{c.preventDefault(),a(o(r)),l(),r.hide()})}),{dialog:r})}}var Gh={extends:Mo,data:{targets:"> .uk-parent",toggle:"> a",content:"> ul"}};const Ns="uk-navbar-transparent";var Xh={extends:Ho,props:{dropbarTransparentMode:Boolean},data:{clsDrop:"uk-navbar-dropdown",selNavItem:".uk-navbar-nav > li > a,a.uk-navbar-item,button.uk-navbar-item,.uk-navbar-item a,.uk-navbar-item button,.uk-navbar-toggle",dropbarTransparentMode:!1},computed:{navbarContainer:(t,e)=>e.closest(".uk-navbar-container")},watch:{items(){const t=x(this.$el,"uk-navbar-justify"),e=D(".uk-navbar-nav, .uk-navbar-left, .uk-navbar-right",this.$el);for(const i of e){const s=t?D(".uk-navbar-nav > li > a, .uk-navbar-item, .uk-navbar-toggle",i).length:"";h(i,"flexGrow",s)}}},events:[{name:"show",el:({dropContainer:t})=>t,handler({target:t}){this.getTransparentMode(t)==="remove"&&x(this.navbarContainer,Ns)&&(_(this.navbarContainer,Ns),this._transparent=!0)}},{name:"hide",el:({dropContainer:t})=>t,async handler(){await Jh(),this._transparent&&(!Y||!this.dropContainer.contains(Y.$el))&&(S(this.navbarContainer,Ns),this._transparent=null)}}],methods:{getTransparentMode(t){if(!this.navbarContainer)return;if(this.dropbar&&this.isDropbarDrop(t))return this.dropbarTransparentMode;const e=this.getDropdown(t);if(e&&x(t,"uk-dropbar"))return e.inset?"behind":"remove"},getDropbarOffset(t){const{top:e,height:i}=E(this.navbarContainer);return e+(this.dropbarTransparentMode==="behind"?0:i+t)}}};function Jh(){return new Promise(t=>setTimeout(t))}var Kh={mixins:[Es],args:"mode",props:{mode:String,flip:Boolean,overlay:Boolean,swiping:Boolean},data:{mode:"slide",flip:!1,overlay:!1,clsPage:"uk-offcanvas-page",clsContainer:"uk-offcanvas-container",selPanel:".uk-offcanvas-bar",clsFlip:"uk-offcanvas-flip",clsContainerAnimation:"uk-offcanvas-container-animation",clsSidebarAnimation:"uk-offcanvas-bar-animation",clsMode:"uk-offcanvas",clsOverlay:"uk-offcanvas-overlay",selClose:".uk-offcanvas-close",container:!1,swiping:!0},computed:{clsFlip:({flip:t,clsFlip:e})=>t?e:"",clsOverlay:({overlay:t,clsOverlay:e})=>t?e:"",clsMode:({mode:t,clsMode:e})=>`${e}-${t}`,clsSidebarAnimation:({mode:t,clsSidebarAnimation:e})=>t==="none"||t==="reveal"?"":e,clsContainerAnimation:({mode:t,clsContainerAnimation:e})=>t!=="push"&&t!=="reveal"?"":e,transitionElement({mode:t}){return t==="reveal"?O(this.panel):this.panel}},observe:In({filter:({swiping:t})=>t}),update:{read(){this.isToggled()&&!q(this.$el)&&this.hide()},events:["resize"]},events:[{name:"touchmove",self:!0,passive:!1,filter:({overlay:t})=>t,handler(t){t.cancelable&&t.preventDefault()}},{name:"show",self:!0,handler(){this.mode==="reveal"&&!x(O(this.panel),this.clsMode)&&S(Ne(this.panel,"<div>"),this.clsMode);const{body:t,scrollingElement:e}=document;S(t,this.clsContainer,this.clsFlip),h(t,"touchAction","pan-y pinch-zoom"),h(this.$el,"display","block"),h(this.panel,"maxWidth",e.clientWidth),S(this.$el,this.clsOverlay),S(this.panel,this.clsSidebarAnimation,this.mode==="reveal"?"":this.clsMode),et(t),S(t,this.clsContainerAnimation),this.clsContainerAnimation&&Zh()}},{name:"hide",self:!0,handler(){_(document.body,this.clsContainerAnimation),h(document.body,"touchAction","")}},{name:"hidden",self:!0,handler(){this.clsContainerAnimation&&Qh(),this.mode==="reveal"&&x(O(this.panel),this.clsMode)&&ze(this.panel),_(this.panel,this.clsSidebarAnimation,this.clsMode),_(this.$el,this.clsOverlay),h(this.$el,"display",""),h(this.panel,"maxWidth",""),_(document.body,this.clsContainer,this.clsFlip)}},{name:"swipeLeft swipeRight",handler(t){this.isToggled()&&ee(t.type,"Left")^this.flip&&this.hide()}}]};function Zh(){Go().content+=",user-scalable=0"}function Qh(){const t=Go();t.content=t.content.replace(/,user-scalable=0$/,"")}function Go(){return $('meta[name="viewport"]',document.head)||W(document.head,'<meta name="viewport">')}var tc={mixins:[it],props:{selContainer:String,selContent:String,minHeight:Number},data:{selContainer:".uk-modal",selContent:".uk-modal-dialog",minHeight:150},computed:{container:({selContainer:t},e)=>e.closest(t),content:({selContent:t},e)=>e.closest(t)},observe:dt({target:({container:t,content:e})=>[t,e]}),update:{read(){return!this.content||!this.container||!q(this.$el)?!1:{max:Math.max(this.minHeight,et(this.container)-(m(this.content).height-et(this.$el)))}},write({max:t}){h(this.$el,{minHeight:this.minHeight,maxHeight:t})},events:["resize"]}},ec={props:["width","height"],connected(){S(this.$el,"uk-responsive-width"),h(this.$el,"aspectRatio",`${this.width}/${this.height}`)}},ic={props:{offset:Number},data:{offset:0},connected(){sc(this)},disconnected(){nc(this)},methods:{async scrollTo(t){t=t&&$(t)||document.body,v(this.$el,"beforescroll",[this,t])&&(await pn(t,{offset:this.offset}),v(this.$el,"scrolled",[this,t]))}}};const Ze=new Set;function sc(t){Ze.size||y(document,"click",Xo),Ze.add(t)}function nc(t){Ze.delete(t),Ze.size||Rt(document,"click",Xo)}function Xo(t){if(!t.defaultPrevented)for(const e of Ze)e.$el.contains(t.target)&&ce(e.$el)&&(t.preventDefault(),window.location.href!==e.$el.href&&window.history.pushState({},"",e.$el.href),e.scrollTo(Ui(e.$el)))}const zs="uk-scrollspy-inview";var oc={args:"cls",props:{cls:String,target:String,hidden:Boolean,margin:String,repeat:Boolean,delay:Number},data:()=>({cls:"",target:!1,hidden:!0,margin:"-1px",repeat:!1,delay:0}),computed:{elements:({target:t},e)=>t?D(t,e):[e]},watch:{elements(t){this.hidden&&h(Oe(t,`:not(.${zs})`),"opacity",0)}},connected(){this.elementData=new Map},disconnected(){for(const[t,e]of this.elementData.entries())_(t,zs,(e==null?void 0:e.cls)||"");delete this.elementData},observe:ge({target:({elements:t})=>t,handler(t){const e=this.elementData;for(const{target:i,isIntersecting:s}of t){e.has(i)||e.set(i,{cls:Z(i,"uk-scrollspy-class")||this.cls});const n=e.get(i);!this.repeat&&n.show||(n.show=s)}this.$emit()},options:({margin:t})=>({rootMargin:t}),args:{intersecting:!1}}),update:[{write(t){for(const[e,i]of this.elementData.entries())i.show&&!i.inview&&!i.queued?(i.queued=!0,t.promise=(t.promise||Promise.resolve()).then(()=>new Promise(s=>setTimeout(s,this.delay))).then(()=>{this.toggle(e,!0),setTimeout(()=>{i.queued=!1,this.$emit()},300)})):!i.show&&i.inview&&!i.queued&&this.repeat&&this.toggle(e,!1)}}],methods:{toggle(t,e){var i,s;const n=(i=this.elementData)==null?void 0:i.get(t);if(!n)return;(s=n.off)==null||s.call(n),h(t,"opacity",!e&&this.hidden?0:""),H(t,zs,e),H(t,n.cls);let o;if(o=n.cls.match(/\buk-animation-[\w-]+/g)){const r=()=>_(t,o);e?n.off=L(t,"animationcancel animationend",r,{self:!0}):r()}v(t,e?"inview":"outview"),n.inview=e}}},rc={props:{cls:String,closest:Boolean,scroll:Boolean,target:String,offset:Number},data:{cls:"uk-active",closest:!1,scroll:!1,target:'a[href]:not([role="button"])',offset:0},computed:{links:({target:t},e)=>D(t,e).filter(i=>ce(i)),elements({closest:t}){return this.links.map(e=>e.closest(t||"*"))}},watch:{links(t){this.scroll&&this.$create("scroll",t,{offset:this.offset})}},observe:[ge(),Re()],update:[{read(){const t=this.links.map(l=>Ui(l)).filter(Boolean),{length:e}=t;if(!e||!q(this.$el))return!1;const i=Ot(t,!0),{scrollTop:s,scrollHeight:n}=i,o=rt(i),r=n-o.height;let a=!1;if(s>=r)a=e-1;else{const l=this.offset+m(us()).height+o.height*.1;for(let c=0;c<t.length&&!(E(t[c]).top-o.top-l>0);c++)a=+c}return{active:a}},write({active:t}){const e=t!==!1&&!x(this.elements[t],this.cls);this.links.forEach(i=>i.blur());for(let i=0;i<this.elements.length;i++)H(this.elements[i],this.cls,+i===t);e&&v(this.$el,"active",[t,this.elements[t]])},events:["scroll","resize"]}]},ac={mixins:[it,Ei],props:{position:String,top:null,bottom:null,start:null,end:null,offset:String,offsetEnd:String,overflowFlip:Boolean,animation:String,clsActive:String,clsInactive:String,clsFixed:String,clsBelow:String,selTarget:String,showOnUp:Boolean,targetOffset:Number},data:{position:"top",top:!1,bottom:!1,start:!1,end:!1,offset:0,offsetEnd:0,overflowFlip:!1,animation:"",clsActive:"uk-active",clsInactive:"",clsFixed:"uk-sticky-fixed",clsBelow:"uk-sticky-below",selTarget:"",showOnUp:!1,targetOffset:!1},computed:{target:({selTarget:t},e)=>t&&$(t,e)||e},connected(){this.start=Jo(this.start||this.top),this.end=Jo(this.end||this.bottom),this.placeholder=$("+ .uk-sticky-placeholder",this.$el)||$('<div class="uk-sticky-placeholder"></div>'),this.isFixed=!1,this.setActive(!1)},beforeDisconnect(){this.isFixed&&(this.hide(),_(this.target,this.clsInactive)),Ko(this.$el),Q(this.placeholder),this.placeholder=null},observe:[vs(),Re({target:()=>document.scrollingElement}),dt({target:({$el:t})=>[t,zi(t),document.scrollingElement],handler(t){this.$emit(this._data.resized&&t.some(({target:e})=>e===zi(this.$el))?"update":"resize"),this._data.resized=!0}})],events:[{name:"load hashchange popstate",el:()=>window,filter:({targetOffset:t})=>t!==!1,handler(){const{scrollingElement:t}=document;!location.hash||t.scrollTop===0||setTimeout(()=>{const e=E($(location.hash)),i=E(this.$el);this.isFixed&&ii(e,i)&&(t.scrollTop=Math.ceil(e.top-i.height-G(this.targetOffset,"height",this.placeholder)-G(this.offset,"height",this.placeholder)))})}}],update:[{read({height:t,width:e,margin:i,sticky:s},n){if(this.inactive=!this.matchMedia||!q(this.$el)||!this.$el.offsetHeight,this.inactive)return;const o=et(window),r=Math.max(0,document.scrollingElement.scrollHeight-o);if(!r){this.inactive=!0;return}const a=this.isFixed&&n.has("update");a&&(Ls(this.target),this.hide()),this.active||({height:t,width:e}=m(this.$el),i=h(this.$el,"margin")),a&&this.show();const l=G("100vh","height");let c=this.position;this.overflowFlip&&t>l&&(c=c==="top"?"bottom":"top");const u=this.isFixed?this.placeholder:this.$el;let[d,f]=[this.offset,this.offsetEnd].map(Mt=>G(Mt,"height",s?this.$el:u));c==="bottom"&&(t<o||this.overflowFlip)&&(d+=o-t);const g=t+d+f,w=this.overflowFlip?0:Math.max(0,g-l),I=E(u).top-new DOMMatrix(h(u,"transform")).m42,P=m(this.$el).height,ht=(this.start===!1?I:Fs(this.start,this.$el,I))-d,It=this.end===!1?r:Math.min(r,Fs(this.end,this.$el,I+t,!0)-P-d+w);return s=!this.showOnUp&&ht+d===I&&It===Math.min(r,Fs(!0,this.$el,0,!0)-P-d+w)&&h(zi(this.$el),"overflowY")!=="hidden",{start:ht,end:It,offset:d,overflow:w,height:t,elHeight:P,width:e,margin:i,top:Fe(u)[0],sticky:s,viewport:l,maxScrollHeight:r}},write({height:t,width:e,margin:i,offset:s,sticky:n}){if((this.inactive||n||!this.isFixed)&&Ko(this.$el),this.inactive)return;n&&(t=e=i=0,h(this.$el,{position:"sticky",top:s}));const{placeholder:o}=this;h(o,{height:t,width:e,margin:i}),(O(o)!==O(this.$el)||n^yt(o)<yt(this.$el))&&((n?ui:di)(this.$el,o),o.hidden=!0)},events:["resize"]},{read({scroll:t=0,dir:e="down",overflow:i,overflowScroll:s=0,start:n,end:o,elHeight:r,height:a,sticky:l,maxScrollHeight:c}){const u=Math.min(document.scrollingElement.scrollTop,c),d=t<=u?"down":"up",f=this.isFixed?this.placeholder:this.$el;return{dir:d,prevDir:e,scroll:u,prevScroll:t,below:u>E(f).top+(l?Math.min(a,r):a),offsetParentTop:E(f.offsetParent).top,overflowScroll:K(s+K(u,n,o)-K(t,n,o),0,i)}},write(t,e){const i=e.has("scroll"),{initTimestamp:s=0,dir:n,prevDir:o,scroll:r,prevScroll:a=0,top:l,start:c,below:u}=t;if(r<0||r===a&&i||this.showOnUp&&!i&&!this.isFixed)return;const d=Date.now();if((d-s>300||n!==o)&&(t.initScroll=r,t.initTimestamp=d),!(this.showOnUp&&!this.isFixed&&Math.abs(t.initScroll-r)<=30&&Math.abs(a-r)<=10))if(this.inactive||r<c||this.showOnUp&&(r<=c||n==="down"&&i||n==="up"&&!this.isFixed&&!u)){if(!this.isFixed){Pt.inProgress(this.$el)&&l>r&&(Pt.cancel(this.$el),this.hide());return}if(this.animation&&u){if(x(this.$el,"uk-animation-leave"))return;Pt.out(this.$el,this.animation).then(()=>this.hide(),A)}else this.hide()}else this.isFixed?this.update():this.animation&&u?(this.show(),Pt.in(this.$el,this.animation).catch(A)):(Ls(this.target),this.show())},events:["resize","resizeViewport","scroll"]}],methods:{show(){this.isFixed=!0,this.update(),this.placeholder.hidden=!1},hide(){const{offset:t,sticky:e}=this._data;this.setActive(!1),_(this.$el,this.clsFixed,this.clsBelow),e?h(this.$el,"top",t):h(this.$el,{position:"",top:"",width:"",marginTop:""}),this.placeholder.hidden=!0,this.isFixed=!1},update(){let{width:t,scroll:e=0,overflow:i,overflowScroll:s=0,start:n,end:o,offset:r,offsetParentTop:a,sticky:l,below:c}=this._data;const u=n!==0||e>n;if(!l){let d="fixed";e>o&&(r+=o-a+s-i,d="absolute"),h(this.$el,{position:d,width:t,marginTop:0},"important")}h(this.$el,"top",r-s),this.setActive(u),H(this.$el,this.clsBelow,c),S(this.$el,this.clsFixed)},setActive(t){const e=this.active;this.active=t,t?(ni(this.target,this.clsInactive,this.clsActive),e!==t&&v(this.$el,"active")):(ni(this.target,this.clsActive,this.clsInactive),e!==t&&(Ls(this.target),v(this.$el,"inactive")))}}};function Fs(t,e,i,s){if(!t)return 0;if(vt(t)||F(t)&&t.match(/^-?\d/))return i+G(t,"height",e,!0);{const n=t===!0?zi(e):tt(t,e);return E(n).bottom-(s&&(n!=null&&n.contains(e))?k(h(n,"paddingBottom"))+k(h(n,"borderBottomWidth")):0)}}function Jo(t){return t==="true"?!0:t==="false"?!1:t}function Ko(t){h(t,{position:"",top:"",marginTop:"",width:""})}const Hs="uk-transition-disable";function Ls(t){x(t,Hs)||(S(t,Hs),requestAnimationFrame(()=>_(t,Hs)))}function zi(t){for(;t=O(t);)if(q(t))return t}var lc={mixins:[Ro],args:"src",props:{src:String,icon:String,attributes:"list",strokeAnimation:Boolean},data:{strokeAnimation:!1},observe:[$i({async handler(){const t=await this.svg;t&&Zo.call(this,t)},options:{attributes:!0,attributeFilter:["id","class","style"]}})],async connected(){b(this.src,"#")&&([this.src,this.icon]=this.src.split("#",2));const t=await this.svg;t&&(Zo.call(this,t),this.strokeAnimation&&cc(t))},methods:{async getSvg(){return z(this.$el,"img")&&!this.$el.complete&&this.$el.loading==="lazy"&&await new Promise(t=>L(this.$el,"load",t)),Uo(await hc(this.src),this.icon)||Promise.reject("SVG not found.")}}};function Zo(t){const{$el:e}=this;S(t,p(e,"class"),"uk-svg");for(let i=0;i<e.style.length;i++){const s=e.style[i];h(t,s,h(e,s))}for(const i in this.attributes){const[s,n]=this.attributes[i].split(":",2);p(t,s,n)}this.$el.id||Pe(t,"id")}const hc=ct(async t=>{if(t){if(mt(t,"data:"))return decodeURIComponent(t.split(",",2)[1]);{const e=await fetch(t);if(e.headers.get("Content-Type")==="image/svg+xml")return e.text()}}return Promise.reject()});function cc(t){const e=lo(t);e&&h(t,"--uk-animation-stroke",e)}const Ws=".uk-disabled *, .uk-disabled, [disabled]";var Qo={mixins:[Yt],args:"connect",props:{connect:String,toggle:String,itemNav:String,active:Number,followFocus:Boolean,swiping:Boolean},data:{connect:"~.uk-switcher",toggle:"> * > :first-child",itemNav:!1,active:0,cls:"uk-active",attrItem:"uk-switcher-item",selVertical:".uk-nav",followFocus:!1,swiping:!0},computed:{connects:{get:({connect:t},e)=>De(t,e),observe:({connect:t})=>t},connectChildren(){return this.connects.map(t=>B(t)).flat()},toggles:({toggle:t},e)=>D(t,e),children(t,e){return B(e).filter(i=>this.toggles.some(s=>i.contains(s)))}},watch:{connects(t){this.swiping&&h(t,"touchAction","pan-y pinch-zoom"),this.$emit()},connectChildren(){let t=Math.max(0,this.index());for(const e of this.connects)B(e).forEach((i,s)=>H(i,this.cls,s===t));this.$emit()},toggles(t){this.$emit();const e=this.index();this.show(~e?e:t[this.active]||t[0])}},connected(){p(this.$el,"role","tablist")},observe:[yi({targets:({connectChildren:t})=>t}),In({target:({connects:t})=>t,filter:({swiping:t})=>t})],events:[{name:"click keydown",delegate:({toggle:t})=>t,handler(t){!C(t.current,Ws)&&(t.type==="click"||t.keyCode===M.SPACE)&&(t.preventDefault(),this.show(t.current))}},{name:"keydown",delegate:({toggle:t})=>t,handler(t){const{current:e,keyCode:i}=t,s=C(this.$el,this.selVertical);let n=i===M.HOME?0:i===M.END?"last":i===M.LEFT&&!s||i===M.UP&&s?"previous":i===M.RIGHT&&!s||i===M.DOWN&&s?"next":-1;if(~n){t.preventDefault();const o=this.toggles.filter(a=>!C(a,Ws)),r=o[ot(n,o,o.indexOf(e))];r.focus(),this.followFocus&&this.show(r)}}},{name:"click",el:({$el:t,connects:e,itemNav:i})=>e.concat(i?De(i,t):[]),delegate:({attrItem:t})=>`[${t}],[data-${t}]`,handler(t){t.target.closest("a,button")&&(t.preventDefault(),this.show(Z(t.current,this.attrItem)))}},{name:"swipeRight swipeLeft",filter:({swiping:t})=>t,el:({connects:t})=>t,handler({type:t}){this.show(ee(t,"Left")?"next":"previous")}}],update(){var t;for(const e of this.connects)z(e,"ul")&&p(e,"role","presentation");p(B(this.$el),"role","presentation");for(const e in this.toggles){const i=this.toggles[e],s=(t=this.connects[0])==null?void 0:t.children[e];p(i,"role","tab"),s&&(i.id=Jt(this,i),s.id=Jt(this,s),p(i,"aria-controls",s.id),p(s,{role:"tabpanel","aria-labelledby":i.id}))}p(this.$el,"aria-orientation",C(this.$el,this.selVertical)?"vertical":null)},methods:{index(){return xt(this.children,t=>x(t,this.cls))},show(t){const e=this.toggles.filter(r=>!C(r,Ws)),i=this.index(),s=ot(!Te(t)||b(e,t)?t:0,e,ot(this.toggles[i],e)),n=ot(e[s],this.toggles);this.children.forEach((r,a)=>{H(r,this.cls,n===a),p(this.toggles[a],{"aria-selected":n===a,tabindex:n===a?null:-1})});const o=i>=0&&i!==s;this.connects.forEach(async({children:r})=>{const a=ie(r).filter((l,c)=>c!==n&&x(l,this.cls));await this.toggleElement(a,!1,o)&&await this.toggleElement(r[n],!0,o)})}}},uc={mixins:[it],extends:Qo,props:{media:Boolean},data:{media:960,attrItem:"uk-tab-item",selVertical:".uk-tab-left,.uk-tab-right"},connected(){const t=x(this.$el,"uk-tab-left")?"uk-tab-left":x(this.$el,"uk-tab-right")?"uk-tab-right":!1;t&&this.$create("toggle",this.$el,{cls:t,mode:"media",media:this.media})}};const dc=32;var fc={mixins:[Ei,Yt],args:"target",props:{href:String,target:null,mode:"list",queued:Boolean},data:{href:!1,target:!1,mode:"click",queued:!0},computed:{target:{get:({target:t},e)=>(t=De(t||e.hash,e),t.length?t:[e]),observe:({target:t})=>t}},connected(){b(this.mode,"media")||(li(this.$el)||p(this.$el,"tabindex","0"),!this.cls&&z(this.$el,"a")&&p(this.$el,"role","button"))},observe:yi({targets:({target:t})=>t}),events:[{name:ut,filter:({mode:t})=>b(t,"hover"),handler(t){this._preventClick=null,!(!pt(t)||ne(this._showState)||this.$el.disabled)&&(v(this.$el,"focus"),L(document,ut,()=>v(this.$el,"blur"),!0,e=>!this.$el.contains(e.target)),b(this.mode,"click")&&(this._preventClick=!0))}},{name:`mouseenter mouseleave ${jt} ${le} focus blur`,filter:({mode:t})=>b(t,"hover"),handler(t){if(pt(t)||this.$el.disabled||document.readyState==="loading")return;const e=b(["mouseenter",jt,"focus"],t.type),i=this.isToggled(this.target);if(!e&&(!ne(this._showState)||t.type!=="blur"&&C(this.$el,":focus")||t.type==="blur"&&C(this.$el,":hover"))){i===this._showState&&(this._showState=null);return}e&&ne(this._showState)&&i!==this._showState||(this._showState=e?i:null,this.toggle(`toggle${e?"show":"hide"}`))}},{name:"keydown",filter:({$el:t,mode:e})=>b(e,"click")&&!z(t,"input"),handler(t){t.keyCode===dc&&(t.preventDefault(),this.$el.click())}},{name:"click",filter:({mode:t})=>["click","hover"].some(e=>b(t,e)),handler(t){let e;(this._preventClick||t.target.closest('a[href="#"], a[href=""]')||(e=t.target.closest("a[href]"))&&(!this.isToggled(this.target)||e.hash&&C(this.target,e.hash)))&&t.preventDefault(),!this._preventClick&&b(this.mode,"click")&&this.toggle()}},{name:"mediachange",filter:({mode:t})=>b(t,"media"),el:({target:t})=>t,handler(t,e){e.matches^this.isToggled(this.target)&&this.toggle()}}],methods:{async toggle(t){if(!v(this.target,t||"toggle",[this]))return;if(Et(this.$el,"aria-expanded")&&p(this.$el,"aria-expanded",!this.isToggled(this.target)),!this.queued)return this.toggleElement(this.target);const e=this.target.filter(s=>x(s,this.clsLeave));if(e.length){for(const s of this.target){const n=b(e,s);this.toggleElement(s,n,n)}return}const i=this.target.filter(this.isToggled);await this.toggleElement(i,!1)&&await this.toggleElement(this.target.filter(s=>!b(i,s)),!0)}}},pc=Object.freeze({__proto__:null,Accordion:Mo,Alert:Wl,Close:Dh,Cover:ql,Drop:zo,DropParentIcon:Zt,Dropdown:zo,Dropnav:Ho,FormCustom:Kl,Grid:Zl,HeightMatch:ih,HeightPlaceholder:oh,HeightViewport:rh,Icon:Bs,Img:ha,Inverse:jh,Leader:Uh,Margin:Tn,Marker:Mh,Modal:Vh,Nav:Gh,NavParentIcon:Ph,Navbar:Xh,NavbarParentIcon:Zt,NavbarToggleIcon:Oh,Offcanvas:Kh,OverflowAuto:tc,OverlayIcon:Zt,PaginationNext:Nh,PaginationPrevious:zh,Responsive:ec,Scroll:ic,Scrollspy:oc,ScrollspyNav:rc,SearchIcon:_h,SlidenavNext:Yo,SlidenavPrevious:Yo,Spinner:Ah,Sticky:ac,Svg:lc,Switcher:Qo,Tab:uc,Toggle:fc,Totop:Bh,Video:Bo});return oe(pc,(t,e)=>lt.component(e,t)),Nl(lt),oe(Bl,(t,e)=>lt.component(e,t)),lt});

/*! UIkit 3.22.0 | https://www.getuikit.com | (c) 2014 - 2025 YOOtheme | MIT License */(function(e,i){typeof exports=="object"&&typeof module<"u"?module.exports=i():typeof define=="function"&&define.amd?define("uikiticons",i):(e=typeof globalThis<"u"?globalThis:e||self,e.UIkitIcons=i())})(this,function(){"use strict";function e(i){e.installed||i.icon.add({youtube:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M15,4.1c1,0.1,2.3,0,3,0.8c0.8,0.8,0.9,2.1,0.9,3.1C19,9.2,19,10.9,19,12c-0.1,1.1,0,2.4-0.5,3.4c-0.5,1.1-1.4,1.5-2.5,1.6 c-1.2,0.1-8.6,0.1-11,0c-1.1-0.1-2.4-0.1-3.2-1c-0.7-0.8-0.7-2-0.8-3C1,11.8,1,10.1,1,8.9c0-1.1,0-2.4,0.5-3.4C2,4.5,3,4.3,4.1,4.2 C5.3,4.1,12.6,4,15,4.1z M8,7.5v6l5.5-3L8,7.5z"/></svg>',yootheme:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m16.15,5.48c-1.37,0-2.45.61-3.11,1.54-.66-.93-1.74-1.54-3.11-1.54-1.75,0-3.03,1-3.57,2.41v-2.22h-2.01v4.45c0,.85-.31,1.35-1.18,1.35s-1.18-.5-1.18-1.35v-4.45H0v4.86c0,.7.17,1.33.53,1.82.34.49.88.85,1.6,1v3.16h2.1v-3.16c1.28-.28,1.96-1.17,2.1-2.35.52,1.44,1.81,2.48,3.59,2.48,1.37,0,2.45-.61,3.11-1.54.66.93,1.74,1.54,3.11,1.54,2.37,0,3.85-1.82,3.85-4s-1.49-4-3.85-4Zm-6.22,5.99c-1.11,0-1.85-.72-1.85-1.99s.74-1.99,1.85-1.99,1.85.72,1.85,1.99-.74,1.99-1.85,1.99Zm6.22,0c-1.11,0-1.85-.72-1.85-1.99s.74-1.99,1.85-1.99,1.85.72,1.85,1.99-.74,1.99-1.85,1.99Z"/></svg>',yelp:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M17.175,14.971c-0.112,0.77-1.686,2.767-2.406,3.054c-0.246,0.1-0.487,0.076-0.675-0.069	c-0.122-0.096-2.446-3.859-2.446-3.859c-0.194-0.293-0.157-0.682,0.083-0.978c0.234-0.284,0.581-0.393,0.881-0.276	c0.016,0.01,4.21,1.394,4.332,1.482c0.178,0.148,0.263,0.379,0.225,0.646L17.175,14.971L17.175,14.971z M11.464,10.789	c-0.203-0.307-0.199-0.666,0.009-0.916c0,0,2.625-3.574,2.745-3.657c0.203-0.135,0.452-0.141,0.69-0.025	c0.691,0.335,2.085,2.405,2.167,3.199v0.027c0.024,0.271-0.082,0.491-0.273,0.623c-0.132,0.083-4.43,1.155-4.43,1.155	c-0.322,0.096-0.68-0.06-0.882-0.381L11.464,10.789z M9.475,9.563C9.32,9.609,8.848,9.757,8.269,8.817c0,0-3.916-6.16-4.007-6.351	c-0.057-0.212,0.011-0.455,0.202-0.65C5.047,1.211,8.21,0.327,9.037,0.529c0.27,0.069,0.457,0.238,0.522,0.479	c0.047,0.266,0.433,5.982,0.488,7.264C10.098,9.368,9.629,9.517,9.475,9.563z M9.927,19.066c-0.083,0.225-0.273,0.373-0.54,0.421	c-0.762,0.13-3.15-0.751-3.647-1.342c-0.096-0.131-0.155-0.262-0.167-0.394c-0.011-0.095,0-0.189,0.036-0.272	c0.061-0.155,2.917-3.538,2.917-3.538c0.214-0.272,0.595-0.355,0.952-0.213c0.345,0.13,0.56,0.428,0.536,0.749	C10.014,14.479,9.977,18.923,9.927,19.066z M3.495,13.912c-0.235-0.009-0.444-0.148-0.568-0.382c-0.089-0.17-0.151-0.453-0.19-0.794	C2.63,11.701,2.761,10.144,3.07,9.648c0.145-0.226,0.357-0.345,0.592-0.336c0.154,0,4.255,1.667,4.255,1.667	c0.321,0.118,0.521,0.453,0.5,0.833c-0.023,0.37-0.236,0.655-0.551,0.738L3.495,13.912z"/></svg>',xing:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M4.4,4.56 C4.24,4.56 4.11,4.61 4.05,4.72 C3.98,4.83 3.99,4.97 4.07,5.12 L5.82,8.16 L5.82,8.17 L3.06,13.04 C2.99,13.18 2.99,13.33 3.06,13.44 C3.12,13.55 3.24,13.62 3.4,13.62 L6,13.62 C6.39,13.62 6.57,13.36 6.71,13.12 C6.71,13.12 9.41,8.35 9.51,8.16 C9.49,8.14 7.72,5.04 7.72,5.04 C7.58,4.81 7.39,4.56 6.99,4.56 L4.4,4.56 L4.4,4.56 Z"/><path d="M15.3,1 C14.91,1 14.74,1.25 14.6,1.5 C14.6,1.5 9.01,11.42 8.82,11.74 C8.83,11.76 12.51,18.51 12.51,18.51 C12.64,18.74 12.84,19 13.23,19 L15.82,19 C15.98,19 16.1,18.94 16.16,18.83 C16.23,18.72 16.23,18.57 16.16,18.43 L12.5,11.74 L12.5,11.72 L18.25,1.56 C18.32,1.42 18.32,1.27 18.25,1.16 C18.21,1.06 18.08,1 17.93,1 L15.3,1 L15.3,1 Z"/></svg>',x:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m15.08,2.1h2.68l-5.89,6.71,6.88,9.1h-5.4l-4.23-5.53-4.84,5.53H1.59l6.24-7.18L1.24,2.1h5.54l3.82,5.05,4.48-5.05Zm-.94,14.23h1.48L6,3.61h-1.6l9.73,12.71h0Z"/></svg>',world:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="M1,10.5 L19,10.5"/><path fill="none" stroke="#000" d="M2.35,15.5 L17.65,15.5"/><path fill="none" stroke="#000" d="M2.35,5.5 L17.523,5.5"/><path fill="none" stroke="#000" d="M10,19.46 L9.98,19.46 C7.31,17.33 5.61,14.141 5.61,10.58 C5.61,7.02 7.33,3.83 10,1.7 C10.01,1.7 9.99,1.7 10,1.7 L10,1.7 C12.67,3.83 14.4,7.02 14.4,10.58 C14.4,14.141 12.67,17.33 10,19.46 L10,19.46 L10,19.46 L10,19.46 Z"/><circle fill="none" stroke="#000" cx="10" cy="10.5" r="9"/></svg>',wordpress:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M10,0.5c-5.2,0-9.5,4.3-9.5,9.5s4.3,9.5,9.5,9.5c5.2,0,9.5-4.3,9.5-9.5S15.2,0.5,10,0.5L10,0.5L10,0.5z M15.6,3.9h-0.1 c-0.8,0-1.4,0.7-1.4,1.5c0,0.7,0.4,1.3,0.8,1.9c0.3,0.6,0.7,1.3,0.7,2.3c0,0.7-0.3,1.5-0.6,2.7L14.1,15l-3-8.9 c0.5,0,0.9-0.1,0.9-0.1C12.5,6,12.5,5.3,12,5.4c0,0-1.3,0.1-2.2,0.1C9,5.5,7.7,5.4,7.7,5.4C7.2,5.3,7.2,6,7.6,6c0,0,0.4,0.1,0.9,0.1 l1.3,3.5L8,15L5,6.1C5.5,6.1,5.9,6,5.9,6C6.4,6,6.3,5.3,5.9,5.4c0,0-1.3,0.1-2.2,0.1c-0.2,0-0.3,0-0.5,0c1.5-2.2,4-3.7,6.9-3.7 C12.2,1.7,14.1,2.6,15.6,3.9L15.6,3.9L15.6,3.9z M2.5,6.6l3.9,10.8c-2.7-1.3-4.6-4.2-4.6-7.4C1.8,8.8,2,7.6,2.5,6.6L2.5,6.6L2.5,6.6 z M10.2,10.7l2.5,6.9c0,0,0,0.1,0.1,0.1C11.9,18,11,18.2,10,18.2c-0.8,0-1.6-0.1-2.3-0.3L10.2,10.7L10.2,10.7L10.2,10.7z M14.2,17.1 l2.5-7.3c0.5-1.2,0.6-2.1,0.6-2.9c0-0.3,0-0.6-0.1-0.8c0.6,1.2,1,2.5,1,4C18.3,13,16.6,15.7,14.2,17.1L14.2,17.1L14.2,17.1z"/></svg>',whatsapp:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M16.7,3.3c-1.8-1.8-4.1-2.8-6.7-2.8c-5.2,0-9.4,4.2-9.4,9.4c0,1.7,0.4,3.3,1.3,4.7l-1.3,4.9l5-1.3c1.4,0.8,2.9,1.2,4.5,1.2 l0,0l0,0c5.2,0,9.4-4.2,9.4-9.4C19.5,7.4,18.5,5,16.7,3.3 M10.1,17.7L10.1,17.7c-1.4,0-2.8-0.4-4-1.1l-0.3-0.2l-3,0.8l0.8-2.9 l-0.2-0.3c-0.8-1.2-1.2-2.7-1.2-4.2c0-4.3,3.5-7.8,7.8-7.8c2.1,0,4.1,0.8,5.5,2.3c1.5,1.5,2.3,3.4,2.3,5.5 C17.9,14.2,14.4,17.7,10.1,17.7 M14.4,11.9c-0.2-0.1-1.4-0.7-1.6-0.8c-0.2-0.1-0.4-0.1-0.5,0.1c-0.2,0.2-0.6,0.8-0.8,0.9 c-0.1,0.2-0.3,0.2-0.5,0.1c-0.2-0.1-1-0.4-1.9-1.2c-0.7-0.6-1.2-1.4-1.3-1.6c-0.1-0.2,0-0.4,0.1-0.5C8,8.8,8.1,8.7,8.2,8.5 c0.1-0.1,0.2-0.2,0.2-0.4c0.1-0.2,0-0.3,0-0.4C8.4,7.6,7.9,6.5,7.7,6C7.5,5.5,7.3,5.6,7.2,5.6c-0.1,0-0.3,0-0.4,0 c-0.2,0-0.4,0.1-0.6,0.3c-0.2,0.2-0.8,0.8-0.8,2c0,1.2,0.8,2.3,1,2.4c0.1,0.2,1.7,2.5,4,3.5c0.6,0.2,1,0.4,1.3,0.5 c0.6,0.2,1.1,0.2,1.5,0.1c0.5-0.1,1.4-0.6,1.6-1.1c0.2-0.5,0.2-1,0.1-1.1C14.8,12.1,14.6,12,14.4,11.9"/></svg>',warning:'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="10" cy="14" r="1"/><circle fill="none" stroke="#000" stroke-width="1.1" cx="10" cy="10" r="9"/><path d="M10.97,7.72 C10.85,9.54 10.56,11.29 10.56,11.29 C10.51,11.87 10.27,12 9.99,12 C9.69,12 9.49,11.87 9.43,11.29 C9.43,11.29 9.16,9.54 9.03,7.72 C8.96,6.54 9.03,6 9.03,6 C9.03,5.45 9.46,5.02 9.99,5 C10.53,5.01 10.97,5.44 10.97,6 C10.97,6 11.04,6.54 10.97,7.72 L10.97,7.72 Z"/></svg>',vimeo:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M2.065,7.59C1.84,7.367,1.654,7.082,1.468,6.838c-0.332-0.42-0.137-0.411,0.274-0.772c1.026-0.91,2.004-1.896,3.127-2.688 c1.017-0.713,2.365-1.173,3.286-0.039c0.849,1.045,0.869,2.629,1.084,3.891c0.215,1.309,0.421,2.648,0.88,3.901 c0.127,0.352,0.37,1.018,0.81,1.074c0.567,0.078,1.145-0.917,1.408-1.289c0.684-0.987,1.611-2.317,1.494-3.587 c-0.115-1.349-1.572-1.095-2.482-0.773c0.146-1.514,1.555-3.216,2.912-3.792c1.439-0.597,3.579-0.587,4.302,1.036 c0.772,1.759,0.078,3.802-0.763,5.396c-0.918,1.731-2.1,3.333-3.363,4.829c-1.114,1.329-2.432,2.787-4.093,3.422 c-1.897,0.723-3.021-0.686-3.667-2.318c-0.705-1.777-1.056-3.771-1.565-5.621C4.898,8.726,4.644,7.836,4.136,7.191 C3.473,6.358,2.72,7.141,2.065,7.59C1.977,7.502,2.115,7.551,2.065,7.59L2.065,7.59z"/></svg>',"video-camera":'<svg width="20" height="20" viewBox="0 0 20 20"><polygon fill="none" stroke="#000" points="19.5 5.9 19.5 14.1 14.5 10.4 14.5 15.5 .5 15.5 .5 4.5 14.5 4.5 14.5 9.6 19.5 5.9"/></svg>',users:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="7.7" cy="8.6" r="3.5"/><path fill="none" stroke="#000" stroke-width="1.1" d="M1,18.1 C1.7,14.6 4.4,12.1 7.6,12.1 C10.9,12.1 13.7,14.8 14.3,18.3"/><path fill="none" stroke="#000" stroke-width="1.1" d="M11.4,4 C12.8,2.4 15.4,2.8 16.3,4.7 C17.2,6.6 15.7,8.9 13.6,8.9 C16.5,8.9 18.8,11.3 19.2,14.1"/></svg>',user:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="9.9" cy="6.4" r="4.4"/><path fill="none" stroke="#000" stroke-width="1.1" d="M1.5,19 C2.3,14.5 5.8,11.2 10,11.2 C14.2,11.2 17.7,14.6 18.5,19.2"/></svg>',upload:'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="10" y1="15.17" x2="10" y2="3.17"/><polyline fill="none" stroke="#000" points="13.84 6.63 10 2.8 6.16 6.64"/><line fill="#fff" stroke="#000" x1="3.5" y1="17.5" x2="16.5" y2="17.5"/></svg>',unlock:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="13" height="10" fill="none" stroke="#000" x="3.5" y="8.5"/><path fill="none" stroke="#000" d="M6.5,8.5 L6.5,4.9 C6.5,3 8.1,1.5 10,1.5 C11.9,1.5 13.5,3 13.5,4.9"/></svg>',uikit:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="14.4,3.1 11.3,5.1 15,7.3 15,12.9 10,15.7 5,12.9 5,8.5 2,6.8 2,14.8 9.9,19.5 18,14.8 18,5.3"/><polygon points="9.8,4.2 6.7,2.4 9.8,0.4 12.9,2.3"/></svg>',twitter:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M19,4.74 C18.339,5.029 17.626,5.229 16.881,5.32 C17.644,4.86 18.227,4.139 18.503,3.28 C17.79,3.7 17.001,4.009 16.159,4.17 C15.485,3.45 14.526,3 13.464,3 C11.423,3 9.771,4.66 9.771,6.7 C9.771,6.99 9.804,7.269 9.868,7.539 C6.795,7.38 4.076,5.919 2.254,3.679 C1.936,4.219 1.754,4.86 1.754,5.539 C1.754,6.82 2.405,7.95 3.397,8.61 C2.79,8.589 2.22,8.429 1.723,8.149 L1.723,8.189 C1.723,9.978 2.997,11.478 4.686,11.82 C4.376,11.899 4.049,11.939 3.713,11.939 C3.475,11.939 3.245,11.919 3.018,11.88 C3.49,13.349 4.852,14.419 6.469,14.449 C5.205,15.429 3.612,16.019 1.882,16.019 C1.583,16.019 1.29,16.009 1,15.969 C2.635,17.019 4.576,17.629 6.662,17.629 C13.454,17.629 17.17,12 17.17,7.129 C17.17,6.969 17.166,6.809 17.157,6.649 C17.879,6.129 18.504,5.478 19,4.74"/></svg>',twitch:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M5.23,1,2,4.23V15.85H5.88v3.23L9.1,15.85h2.59L17.5,10V1Zm11,8.4L13.62,12H11L8.78,14.24V12H5.88V2.29H16.21Z"/><rect width="1.29" height="3.88" x="12.98" y="4.55"/><rect width="1.29" height="3.88" x="9.43" y="4.55"/></svg>',tv:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="6" height="1" x="7" y="16"/><rect width="19" height="11" fill="none" stroke="#000" x=".5" y="3.5"/></svg>',tumblr:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M6.885,8.598c0,0,0,3.393,0,4.996c0,0.282,0,0.66,0.094,0.942c0.377,1.509,1.131,2.545,2.545,3.11 c1.319,0.472,2.356,0.472,3.676,0c0.565-0.188,1.132-0.659,1.132-0.659l-0.849-2.263c0,0-1.036,0.378-1.603,0.283 c-0.565-0.094-1.226-0.66-1.226-1.508c0-1.603,0-4.902,0-4.902h2.828V5.771h-2.828V2H8.205c0,0-0.094,0.66-0.188,0.942 C7.828,3.791,7.262,4.733,6.603,5.394C5.848,6.147,5,6.43,5,6.43v2.168H6.885z"/></svg>',tripadvisor:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M19.021,7.866C19.256,6.862,20,5.854,20,5.854h-3.346C14.781,4.641,12.504,4,9.98,4C7.363,4,4.999,4.651,3.135,5.876H0	c0,0,0.738,0.987,0.976,1.988c-0.611,0.837-0.973,1.852-0.973,2.964c0,2.763,2.249,5.009,5.011,5.009	c1.576,0,2.976-0.737,3.901-1.879l1.063,1.599l1.075-1.615c0.475,0.611,1.1,1.111,1.838,1.451c1.213,0.547,2.574,0.612,3.825,0.15	c2.589-0.963,3.913-3.852,2.964-6.439c-0.175-0.463-0.4-0.876-0.675-1.238H19.021z M16.38,14.594	c-1.002,0.371-2.088,0.328-3.06-0.119c-0.688-0.317-1.252-0.817-1.657-1.438c-0.164-0.25-0.313-0.52-0.417-0.811	c-0.124-0.328-0.186-0.668-0.217-1.014c-0.063-0.689,0.037-1.396,0.339-2.043c0.448-0.971,1.251-1.71,2.25-2.079	c2.075-0.765,4.375,0.3,5.14,2.366c0.762,2.066-0.301,4.37-2.363,5.134L16.38,14.594L16.38,14.594z M8.322,13.066	c-0.72,1.059-1.935,1.76-3.309,1.76c-2.207,0-4.001-1.797-4.001-3.996c0-2.203,1.795-4.002,4.001-4.002	c2.204,0,3.999,1.8,3.999,4.002c0,0.137-0.024,0.261-0.04,0.396c-0.067,0.678-0.284,1.313-0.648,1.853v-0.013H8.322z M2.472,10.775	c0,1.367,1.112,2.479,2.476,2.479c1.363,0,2.472-1.11,2.472-2.479c0-1.359-1.11-2.468-2.472-2.468	C3.584,8.306,2.473,9.416,2.472,10.775L2.472,10.775z M12.514,10.775c0,1.367,1.104,2.479,2.471,2.479	c1.363,0,2.474-1.108,2.474-2.479c0-1.359-1.11-2.468-2.474-2.468c-1.364,0-2.477,1.109-2.477,2.468H12.514z M3.324,10.775	c0-0.893,0.726-1.618,1.614-1.618c0.889,0,1.625,0.727,1.625,1.618c0,0.898-0.725,1.627-1.625,1.627	c-0.901,0-1.625-0.729-1.625-1.627H3.324z M13.354,10.775c0-0.893,0.726-1.618,1.627-1.618c0.886,0,1.61,0.727,1.61,1.618	c0,0.898-0.726,1.627-1.626,1.627s-1.625-0.729-1.625-1.627H13.354z M9.977,4.875c1.798,0,3.425,0.324,4.849,0.968	c-0.535,0.015-1.061,0.108-1.586,0.3c-1.264,0.463-2.264,1.388-2.815,2.604c-0.262,0.551-0.398,1.133-0.448,1.72	C9.79,7.905,7.677,5.873,5.076,5.82C6.501,5.208,8.153,4.875,9.94,4.875H9.977z"/></svg>',"triangle-up":'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="5 13 10 8 15 13"/></svg>',"triangle-right":'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="8 5 13 10 8 15"/></svg>',"triangle-left":'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="12 5 7 10 12 15"/></svg>',"triangle-down":'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="5 7 15 7 10 12"/></svg>',trash:'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" points="6.5 3 6.5 1.5 13.5 1.5 13.5 3"/><polyline fill="none" stroke="#000" points="4.5 4 4.5 18.5 15.5 18.5 15.5 4"/><rect width="1" height="9" x="8" y="7"/><rect width="1" height="9" x="11" y="7"/><rect width="16" height="1" x="2" y="3"/></svg>',tiktok:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M17.24,6V8.82a6.79,6.79,0,0,1-4-1.28v5.81A5.26,5.26,0,1,1,8,8.1a4.36,4.36,0,0,1,.72.05v2.9A2.57,2.57,0,0,0,7.64,11a2.4,2.4,0,1,0,2.77,2.38V2h2.86a4,4,0,0,0,1.84,3.38A4,4,0,0,0,17.24,6Z"/></svg>',thumbnails:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="5" height="5" fill="none" stroke="#000" x="3.5" y="3.5"/><rect width="5" height="5" fill="none" stroke="#000" x="11.5" y="3.5"/><rect width="5" height="5" fill="none" stroke="#000" x="11.5" y="11.5"/><rect width="5" height="5" fill="none" stroke="#000" x="3.5" y="11.5"/></svg>',threads:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m14.47,9.29c-.08-.04-.16-.08-.25-.11-.14-2.66-1.6-4.18-4.04-4.2-.01,0-.02,0-.03,0-1.46,0-2.67.62-3.42,1.76l1.34.92c.56-.85,1.43-1.03,2.08-1.03,0,0,.01,0,.02,0,.8,0,1.41.24,1.8.69.29.33.48.79.57,1.37-.71-.12-1.48-.16-2.31-.11-2.32.13-3.81,1.49-3.71,3.37.05.95.53,1.77,1.34,2.31.69.45,1.57.67,2.49.62,1.21-.07,2.16-.53,2.83-1.38.5-.64.82-1.48.96-2.52.58.35,1.01.81,1.24,1.36.4.94.43,2.48-.83,3.74-1.1,1.1-2.43,1.58-4.43,1.59-2.22-.02-3.9-.73-4.99-2.12-1.02-1.3-1.55-3.18-1.57-5.58.02-2.4.55-4.28,1.57-5.58,1.09-1.39,2.77-2.1,4.99-2.12,2.24.02,3.95.73,5.08,2.13.56.68.98,1.54,1.25,2.55l1.57-.42c-.33-1.23-.86-2.3-1.58-3.18-1.45-1.79-3.58-2.7-6.32-2.72h-.01c-2.73.02-4.84.94-6.25,2.73-1.26,1.6-1.9,3.82-1.93,6.61h0s0,.01,0,.01c.02,2.79.67,5.01,1.93,6.61,1.41,1.8,3.51,2.71,6.25,2.73h.01c2.43-.02,4.14-.65,5.55-2.06,1.85-1.84,1.79-4.16,1.18-5.58-.44-1.02-1.27-1.84-2.41-2.39Zm-4.2,3.95c-1.02.06-2.07-.4-2.12-1.38-.04-.72.52-1.53,2.19-1.63.19-.01.38-.02.56-.02.61,0,1.17.06,1.69.17-.19,2.41-1.32,2.8-2.32,2.85Z"/></svg>',telegram:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m10,1.09C5.08,1.09,1.09,5.08,1.09,10s3.99,8.91,8.91,8.91,8.91-3.99,8.91-8.91S14.92,1.09,10,1.09Zm4.25,5.8c-.03.36-.23,1.62-.44,2.99-.31,1.93-.64,4.04-.64,4.04,0,0-.05.59-.49.7s-1.16-.36-1.29-.46c-.1-.08-1.93-1.24-2.6-1.8-.18-.15-.39-.46.03-.82.93-.85,2.04-1.91,2.7-2.58.31-.31.62-1.03-.67-.15-1.83,1.26-3.63,2.45-3.63,2.45,0,0-.41.26-1.19.03-.77-.23-1.67-.54-1.67-.54,0,0-.62-.39.44-.8h0s4.46-1.83,6-2.47c.59-.26,2.6-1.08,2.6-1.08,0,0,.93-.36.85.52Z"/></svg>',tag:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="M17.5,3.71 L17.5,7.72 C17.5,7.96 17.4,8.2 17.21,8.39 L8.39,17.2 C7.99,17.6 7.33,17.6 6.93,17.2 L2.8,13.07 C2.4,12.67 2.4,12.01 2.8,11.61 L11.61,2.8 C11.81,2.6 12.08,2.5 12.34,2.5 L16.19,2.5 C16.52,2.5 16.86,2.63 17.11,2.88 C17.35,3.11 17.48,3.4 17.5,3.71 L17.5,3.71 Z"/><circle cx="14" cy="6" r="1"/></svg>',tablet:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="M5,18.5 C4.2,18.5 3.5,17.8 3.5,17 L3.5,3 C3.5,2.2 4.2,1.5 5,1.5 L16,1.5 C16.8,1.5 17.5,2.2 17.5,3 L17.5,17 C17.5,17.8 16.8,18.5 16,18.5 L5,18.5 L5,18.5 L5,18.5 Z"/><circle cx="10.5" cy="16.3" r=".8"/></svg>',"tablet-landscape":'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="M1.5,5 C1.5,4.2 2.2,3.5 3,3.5 L17,3.5 C17.8,3.5 18.5,4.2 18.5,5 L18.5,16 C18.5,16.8 17.8,17.5 17,17.5 L3,17.5 C2.2,17.5 1.5,16.8 1.5,16 L1.5,5 L1.5,5 L1.5,5 Z"/><circle cx="3.7" cy="10.5" r=".8"/></svg>',table:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="18" height="1" x="1" y="3"/><rect width="18" height="1" x="1" y="7"/><rect width="18" height="1" x="1" y="11"/><rect width="18" height="1" x="1" y="15"/></svg>',strikethrough:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M6,13.02 L6.65,13.02 C7.64,15.16 8.86,16.12 10.41,16.12 C12.22,16.12 12.92,14.93 12.92,13.89 C12.92,12.55 11.99,12.03 9.74,11.23 C8.05,10.64 6.23,10.11 6.23,7.83 C6.23,5.5 8.09,4.09 10.4,4.09 C11.44,4.09 12.13,4.31 12.72,4.54 L13.33,4 L13.81,4 L13.81,7.59 L13.16,7.59 C12.55,5.88 11.52,4.89 10.07,4.89 C8.84,4.89 7.89,5.69 7.89,7.03 C7.89,8.29 8.89,8.78 10.88,9.45 C12.57,10.03 14.38,10.6 14.38,12.91 C14.38,14.75 13.27,16.93 10.18,16.93 C9.18,16.93 8.17,16.69 7.46,16.39 L6.52,17 L6,17 L6,13.02 L6,13.02 Z"/><rect width="15" height="1" x="3" y="10"/></svg>',star:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon fill="none" stroke="#000" stroke-width="1.01" points="10 2 12.63 7.27 18.5 8.12 14.25 12.22 15.25 18 10 15.27 4.75 18 5.75 12.22 1.5 8.12 7.37 7.27"/></svg>',soundcloud:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M17.2,9.4c-0.4,0-0.8,0.1-1.101,0.2c-0.199-2.5-2.399-4.5-5-4.5c-0.6,0-1.2,0.1-1.7,0.3C9.2,5.5,9.1,5.6,9.1,5.6V15h8 c1.601,0,2.801-1.2,2.801-2.8C20,10.7,18.7,9.4,17.2,9.4L17.2,9.4z"/><rect width="1.5" height="8.5" x="6" y="6.5"/><rect width="1.5" height="7" x="3" y="8"/><rect width="1.5" height="5" y="10"/></svg>',sorting:'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="7" y1="3.38" x2="7" y2="15.38"/><polyline fill="none" stroke="#000" points="10.18 12.75 7 15.93 3.83 12.76"/><line fill="none" stroke="#000" x1="13" y1="16.62" x2="13" y2="4.62"/><polyline fill="none" stroke="#000" points="9.82 7.25 13 4.07 16.17 7.24"/></svg>',social:'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" stroke-width="1.1" x1="13.4" y1="14" x2="6.3" y2="10.7"/><line fill="none" stroke="#000" stroke-width="1.1" x1="13.5" y1="5.5" x2="6.5" y2="8.8"/><circle fill="none" stroke="#000" stroke-width="1.1" cx="15.5" cy="4.6" r="2.3"/><circle fill="none" stroke="#000" stroke-width="1.1" cx="15.5" cy="14.8" r="2.3"/><circle fill="none" stroke="#000" stroke-width="1.1" cx="4.5" cy="9.8" r="2.3"/></svg>',signal:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m7.86,1.34l.2.81c-.79.19-1.54.51-2.24.93l-.43-.71c.77-.46,1.6-.81,2.47-1.02Zm4.28,0l-.2.81c.79.19,1.54.51,2.24.93l.43-.72c-.77-.46-1.6-.81-2.47-1.02h0ZM2.37,5.39c-.46.77-.81,1.6-1.02,2.47l.81.2c.19-.79.51-1.54.93-2.24l-.71-.43Zm-.45,4.61c0-.41.03-.81.09-1.21l-.83-.13c-.13.89-.13,1.79,0,2.67l.83-.13c-.06-.4-.09-.81-.09-1.21h0Zm12.69,7.63l-.43-.72c-.7.42-1.45.73-2.24.93l.2.81c.87-.21,1.7-.56,2.46-1.02h0Zm3.47-7.63c0,.41-.03.81-.09,1.21l.83.13c.13-.89.13-1.79,0-2.67l-.83.13c.06.4.09.81.09,1.21Zm.58,2.14l-.81-.2c-.19.79-.51,1.54-.93,2.24l.72.43c.46-.77.81-1.6,1.02-2.47h0Zm-7.44,5.85c-.8.12-1.62.12-2.42,0l-.13.83c.89.13,1.79.13,2.67,0l-.13-.83Zm5.29-3.2c-.48.65-1.06,1.23-1.71,1.71l.5.67c.72-.53,1.36-1.16,1.89-1.88l-.67-.5Zm-1.71-11.29c.65.48,1.23,1.06,1.71,1.71l.67-.5c-.53-.72-1.17-1.35-1.88-1.88l-.5.67Zm-11.29,1.71c.48-.65,1.06-1.23,1.71-1.71l-.5-.67c-.72.53-1.35,1.17-1.88,1.88l.67.5Zm14.14.18l-.72.43c.42.7.73,1.45.93,2.24l.81-.2c-.21-.87-.56-1.7-1.02-2.46h0Zm-8.84-3.38c.8-.12,1.62-.12,2.42,0l.13-.83c-.89-.13-1.79-.13-2.67,0l.13.83Zm-4.86,15.38l-1.73.4.4-1.73-.81-.19-.4,1.73c-.07.28.02.58.22.78s.5.29.78.22l1.73-.39-.19-.82Zm-1.96-2.26l.81.19.28-1.2c-.41-.68-.71-1.42-.9-2.19l-.81.2c.18.74.46,1.45.82,2.12l-.2.88Zm3.9,1.81l-1.19.28.19.81.88-.2c.67.36,1.38.64,2.12.82l.2-.81c-.77-.19-1.51-.5-2.19-.9h0ZM10,2.75c-2.63,0-5.06,1.43-6.34,3.74s-1.19,5.12.21,7.36l-.7,2.97,2.97-.7c2.61,1.64,5.96,1.46,8.37-.46s3.34-5.15,2.32-8.06c-1.02-2.91-3.77-4.85-6.85-4.85Z"/></svg>',"sign-out":'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="13 2 3 2 3 17 13 17 13 16 4 16 4 3 13 3 13 2"/><line stroke="#000" x1="7.96" y1="9.49" x2="16.96" y2="9.49"/><polyline fill="none" stroke="#000" points="14.17 6.31 17.35 9.48 14.17 12.66"/></svg>',"sign-in":'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="7 2 17 2 17 17 7 17 7 16 16 16 16 3 7 3 7 2"/><line stroke="#000" x1="3" y1="9.5" x2="12" y2="9.5"/><polyline fill="none" stroke="#000" points="9.2 6.33 12.37 9.5 9.2 12.67"/></svg>',shrink:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="M2,18l6-6"/><polyline fill="none" stroke="#000" points="4 11.5 8.49 11.5 8.49 15.99"/><path fill="none" stroke="#000" stroke-width="1.1" d="M18,2l-6,6"/><polyline fill="none" stroke="#000" points="15.99 8.49 11.5 8.49 11.5 4"/></svg>',settings:'<svg width="20" height="20" viewBox="0 0 20 20"><ellipse fill="none" stroke="#000" cx="6.11" cy="3.55" rx="2.11" ry="2.15"/><ellipse fill="none" stroke="#000" cx="6.11" cy="15.55" rx="2.11" ry="2.15"/><circle fill="none" stroke="#000" cx="13.15" cy="9.55" r="2.15"/><rect width="3" height="1" x="1" y="3"/><rect width="8" height="1" x="10" y="3"/><rect width="8" height="1" x="1" y="9"/><rect width="3" height="1" x="15" y="9"/><rect width="3" height="1" x="1" y="15"/><rect width="8" height="1" x="10" y="15"/></svg>',server:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="1" height="2" x="3" y="3"/><rect width="1" height="2" x="5" y="3"/><rect width="1" height="2" x="7" y="3"/><rect width="1" height="1" x="16" y="3"/><rect width="1" height="1" x="16" y="10"/><circle fill="none" stroke="#000" cx="9.9" cy="17.4" r="1.4"/><rect width="1" height="2" x="3" y="10"/><rect width="1" height="2" x="5" y="10"/><rect width="1" height="2" x="9.5" y="14"/><rect width="6" height="1" x="3" y="17"/><rect width="6" height="1" x="11" y="17"/><rect width="17" height="5" fill="none" stroke="#000" x="1.5" y="1.5"/><rect width="17" height="5" fill="none" stroke="#000" x="1.5" y="8.5"/></svg>',search:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="9" cy="9" r="7"/><path fill="none" stroke="#000" stroke-width="1.1" d="M14,14 L18,18 L14,14 Z"/></svg>',rss:'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="3.12" cy="16.8" r="1.85"/><path fill="none" stroke="#000" stroke-width="1.1" d="M1.5,8.2 C1.78,8.18 2.06,8.16 2.35,8.16 C7.57,8.16 11.81,12.37 11.81,17.57 C11.81,17.89 11.79,18.19 11.76,18.5"/><path fill="none" stroke="#000" stroke-width="1.1" d="M1.5,2.52 C1.78,2.51 2.06,2.5 2.35,2.5 C10.72,2.5 17.5,9.24 17.5,17.57 C17.5,17.89 17.49,18.19 17.47,18.5"/></svg>',reply:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M17.7,13.11 C16.12,10.02 13.84,7.85 11.02,6.61 C10.57,6.41 9.75,6.13 9,5.91 L9,2 L1,9 L9,16 L9,12.13 C10.78,12.47 12.5,13.19 14.09,14.25 C17.13,16.28 18.56,18.54 18.56,18.54 C18.56,18.54 18.81,15.28 17.7,13.11 L17.7,13.11 Z M14.82,13.53 C13.17,12.4 11.01,11.4 8,10.92 L8,13.63 L2.55,9 L8,4.25 L8,6.8 C8.3,6.86 9.16,7.02 10.37,7.49 C13.3,8.65 15.54,10.96 16.65,13.08 C16.97,13.7 17.48,14.86 17.68,16 C16.87,15.05 15.73,14.15 14.82,13.53 L14.82,13.53 Z"/></svg>',refresh:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="M17.08,11.15 C17.09,11.31 17.1,11.47 17.1,11.64 C17.1,15.53 13.94,18.69 10.05,18.69 C6.16,18.68 3,15.53 3,11.63 C3,7.74 6.16,4.58 10.05,4.58 C10.9,4.58 11.71,4.73 12.46,5"/><polyline fill="none" stroke="#000" points="9.9 2 12.79 4.89 9.79 7.9"/></svg>',reddit:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M19 9.05a2.56 2.56 0 0 0-2.56-2.56 2.59 2.59 0 0 0-1.88.82 10.63 10.63 0 0 0-4.14-1v-.08c.58-1.62 1.58-3.89 2.7-4.1.38-.08.77.12 1.19.57a1.15 1.15 0 0 0-.06.37 1.48 1.48 0 1 0 1.51-1.45 1.43 1.43 0 0 0-.76.19A2.29 2.29 0 0 0 12.91 1c-2.11.43-3.39 4.38-3.63 5.19 0 0 0 .11-.06.11a10.65 10.65 0 0 0-3.75 1A2.56 2.56 0 0 0 1 9.05a2.42 2.42 0 0 0 .72 1.76A5.18 5.18 0 0 0 1.24 13c0 3.66 3.92 6.64 8.73 6.64s8.74-3 8.74-6.64a5.23 5.23 0 0 0-.46-2.13A2.58 2.58 0 0 0 19 9.05zm-16.88 0a1.44 1.44 0 0 1 2.27-1.19 7.68 7.68 0 0 0-2.07 1.91 1.33 1.33 0 0 1-.2-.72zM10 18.4c-4.17 0-7.55-2.4-7.55-5.4S5.83 7.53 10 7.53 17.5 10 17.5 13s-3.38 5.4-7.5 5.4zm7.69-8.61a7.62 7.62 0 0 0-2.09-1.91 1.41 1.41 0 0 1 .84-.28 1.47 1.47 0 0 1 1.44 1.45 1.34 1.34 0 0 1-.21.72z"/><path d="M6.69 12.58a1.39 1.39 0 1 1 1.39-1.39 1.38 1.38 0 0 1-1.38 1.39z"/><path d="M14.26 11.2a1.39 1.39 0 1 1-1.39-1.39 1.39 1.39 0 0 1 1.39 1.39z"/><path d="M13.09 14.88a.54.54 0 0 1-.09.77 5.3 5.3 0 0 1-3.26 1.19 5.61 5.61 0 0 1-3.4-1.22.55.55 0 1 1 .73-.83 4.09 4.09 0 0 0 5.25 0 .56.56 0 0 1 .77.09z"/></svg>',receiver:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.01" d="M6.189,13.611C8.134,15.525 11.097,18.239 13.867,18.257C16.47,18.275 18.2,16.241 18.2,16.241L14.509,12.551L11.539,13.639L6.189,8.29L7.313,5.355L3.76,1.8C3.76,1.8 1.732,3.537 1.7,6.092C1.667,8.809 4.347,11.738 6.189,13.611"/></svg>',"quote-right":'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M17.27,7.79 C17.27,9.45 16.97,10.43 15.99,12.02 C14.98,13.64 13,15.23 11.56,15.97 L11.1,15.08 C12.34,14.2 13.14,13.51 14.02,11.82 C14.27,11.34 14.41,10.92 14.49,10.54 C14.3,10.58 14.09,10.6 13.88,10.6 C12.06,10.6 10.59,9.12 10.59,7.3 C10.59,5.48 12.06,4 13.88,4 C15.39,4 16.67,5.02 17.05,6.42 C17.19,6.82 17.27,7.27 17.27,7.79 L17.27,7.79 Z"/><path d="M8.68,7.79 C8.68,9.45 8.38,10.43 7.4,12.02 C6.39,13.64 4.41,15.23 2.97,15.97 L2.51,15.08 C3.75,14.2 4.55,13.51 5.43,11.82 C5.68,11.34 5.82,10.92 5.9,10.54 C5.71,10.58 5.5,10.6 5.29,10.6 C3.47,10.6 2,9.12 2,7.3 C2,5.48 3.47,4 5.29,4 C6.8,4 8.08,5.02 8.46,6.42 C8.6,6.82 8.68,7.27 8.68,7.79 L8.68,7.79 Z"/></svg>',question:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="10" cy="10" r="9"/><circle cx="9.99" cy="14.24" r="1.05"/><path fill="none" stroke="#000" stroke-width="1.2" d="m7.72,7.61c0-3.04,4.55-3.06,4.55-.07,0,.95-.91,1.43-1.49,2.03-.48.49-.72.98-.78,1.65-.01.13-.02.24-.02.35"/></svg>',push:'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="10" y1="11" x2="10" y2="1"/><polyline fill="none" stroke="#000" points="6.5 6.5 4 6.5 4 19.5 16 19.5 16 6.5 13.5 6.5"/><polyline fill="none" stroke="#000" points="6.82 3.88 10 .71 13.17 3.88"/></svg>',pull:'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="10" y1="11" x2="10" y2="2"/><polyline fill="none" stroke="#000" points="6.5 5.5 4 5.5 4 18.5 16 18.5 16 5.5 13.5 5.5"/><polyline fill="none" stroke="#000" points="13.18 8.2 10 11.38 6.83 8.21"/></svg>',print:'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" points="4.5 13.5 1.5 13.5 1.5 6.5 18.5 6.5 18.5 13.5 15.5 13.5"/><polyline fill="none" stroke="#000" points="15.5 6.5 15.5 2.5 4.5 2.5 4.5 6.5"/><rect width="11" height="6" fill="none" stroke="#000" x="4.5" y="11.5"/><rect width="8" height="1" x="6" y="13"/><rect width="8" height="1" x="6" y="15"/></svg>',plus:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="1" height="17" x="9" y="1"/><rect width="17" height="1" x="1" y="9"/></svg>',"plus-circle":'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="9.5" cy="9.5" r="9"/><line fill="none" stroke="#000" x1="9.5" y1="5" x2="9.5" y2="14"/><line fill="none" stroke="#000" x1="5" y1="9.5" x2="14" y2="9.5"/></svg>',play:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon fill="none" stroke="#000" points="6.5,5 14.5,10 6.5,15"/></svg>',"play-circle":'<svg width="20" height="20" viewBox="0 0 20 20"><polygon fill="none" stroke="#000" stroke-width="1.1" points="8.5 7 13.5 10 8.5 13"/><circle fill="none" stroke="#000" stroke-width="1.1" cx="10" cy="10" r="9"/></svg>',pinterest:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M10.21,1 C5.5,1 3,4.16 3,7.61 C3,9.21 3.85,11.2 5.22,11.84 C5.43,11.94 5.54,11.89 5.58,11.69 C5.62,11.54 5.8,10.8 5.88,10.45 C5.91,10.34 5.89,10.24 5.8,10.14 C5.36,9.59 5,8.58 5,7.65 C5,5.24 6.82,2.91 9.93,2.91 C12.61,2.91 14.49,4.74 14.49,7.35 C14.49,10.3 13,12.35 11.06,12.35 C9.99,12.35 9.19,11.47 9.44,10.38 C9.75,9.08 10.35,7.68 10.35,6.75 C10.35,5.91 9.9,5.21 8.97,5.21 C7.87,5.21 6.99,6.34 6.99,7.86 C6.99,8.83 7.32,9.48 7.32,9.48 C7.32,9.48 6.24,14.06 6.04,14.91 C5.7,16.35 6.08,18.7 6.12,18.9 C6.14,19.01 6.26,19.05 6.33,18.95 C6.44,18.81 7.74,16.85 8.11,15.44 C8.24,14.93 8.79,12.84 8.79,12.84 C9.15,13.52 10.19,14.09 11.29,14.09 C14.58,14.09 16.96,11.06 16.96,7.3 C16.94,3.7 14,1 10.21,1"/></svg>',phone:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="M15.5,17 C15.5,17.8 14.8,18.5 14,18.5 L7,18.5 C6.2,18.5 5.5,17.8 5.5,17 L5.5,3 C5.5,2.2 6.2,1.5 7,1.5 L14,1.5 C14.8,1.5 15.5,2.2 15.5,3 L15.5,17 L15.5,17 L15.5,17 Z"/><circle cx="10.5" cy="16.5" r=".8"/></svg>',"phone-landscape":'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="M17,5.5 C17.8,5.5 18.5,6.2 18.5,7 L18.5,14 C18.5,14.8 17.8,15.5 17,15.5 L3,15.5 C2.2,15.5 1.5,14.8 1.5,14 L1.5,7 C1.5,6.2 2.2,5.5 3,5.5 L17,5.5 L17,5.5 L17,5.5 Z"/><circle cx="3.8" cy="10.5" r=".8"/></svg>',pencil:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="M17.25,6.01 L7.12,16.1 L3.82,17.2 L5.02,13.9 L15.12,3.88 C15.71,3.29 16.66,3.29 17.25,3.88 C17.83,4.47 17.83,5.42 17.25,6.01 L17.25,6.01 Z"/><path fill="none" stroke="#000" d="M15.98,7.268 L13.851,5.148"/></svg>',"paint-bucket":'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="m6.42,2.16l5.28,5.28"/><path d="m18.49,11.83s1.51,2.06,1.51,3.36c0,.92-.76,1.64-1.51,1.64h0c-.75,0-1.49-.72-1.49-1.64,0-1.3,1.49-3.36,1.49-3.36h0Z"/><line fill="none" stroke="#000" x1="1.26" y1="10.5" x2="16" y2="10.5"/><polygon fill="none" stroke="#000" stroke-width="1.1" points="10.2 1.55 17.6 8.93 8.08 18.45 .7 11.07 10.2 1.55"/></svg>',nut:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon fill="none" stroke="#000" points="2.5,5.7 10,1.3 17.5,5.7 17.5,14.3 10,18.7 2.5,14.3"/><circle fill="none" stroke="#000" cx="10" cy="10" r="3.5"/></svg>',move:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="4,5 1,5 1,9 2,9 2,6 4,6"/><polygon points="1,16 2,16 2,18 4,18 4,19 1,19"/><polygon points="14,16 14,19 11,19 11,18 13,18 13,16"/><rect width="13" height="13" fill="none" stroke="#000" x="5.5" y="1.5"/><rect width="1" height="3" x="1" y="11"/><rect width="3" height="1" x="6" y="18"/></svg>',more:'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="3" cy="10" r="2"/><circle cx="10" cy="10" r="2"/><circle cx="17" cy="10" r="2"/></svg>',"more-vertical":'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="10" cy="3" r="2"/><circle cx="10" cy="10" r="2"/><circle cx="10" cy="17" r="2"/></svg>',minus:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="18" height="1" x="1" y="9"/></svg>',"minus-circle":'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="9.5" cy="9.5" r="9"/><line fill="none" stroke="#000" x1="5" y1="9.5" x2="14" y2="9.5"/></svg>',microsoft:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m2,2h7.58v7.58H2V2Zm8.42,0h7.58v7.58h-7.58V2ZM2,10.42h7.58v7.58H2v-7.58Zm8.42,0h7.58v7.58h-7.58"/></svg>',microphone:'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="10" y1="16.44" x2="10" y2="18.5"/><line fill="none" stroke="#000" x1="7" y1="18.5" x2="13" y2="18.5"/><path fill="none" stroke="#000" stroke-width="1.1" d="M13.5 4.89v5.87a3.5 3.5 0 0 1-7 0V4.89a3.5 3.5 0 0 1 7 0z"/><path fill="none" stroke="#000" stroke-width="1.1" d="M15.5 10.36V11a5.5 5.5 0 0 1-11 0v-.6"/></svg>',menu:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="16" height="1" x="2" y="4"/><rect width="16" height="1" x="2" y="9"/><rect width="16" height="1" x="2" y="14"/></svg>',mastodon:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m18.5,6.87c0-3.95-2.59-5.11-2.59-5.11-1.31-.6-3.55-.85-5.88-.87h-.06c-2.33.02-4.57.27-5.88.87,0,0-2.59,1.16-2.59,5.11,0,.91-.02,1.99.01,3.14.09,3.87.71,7.68,4.28,8.62,1.65.44,3.06.53,4.2.47,2.07-.11,3.23-.74,3.23-.74l-.07-1.5s-1.48.47-3.14.41c-1.64-.06-3.38-.18-3.64-2.2-.02-.18-.04-.37-.04-.57,0,0,1.61.39,3.66.49,1.25.06,2.42-.07,3.61-.22,2.28-.27,4.27-1.68,4.52-2.97.39-2.02.36-4.94.36-4.94Zm-3.05,5.09h-1.9v-4.65c0-.98-.41-1.48-1.24-1.48-.91,0-1.37.59-1.37,1.76v2.54h-1.89v-2.54c0-1.17-.46-1.76-1.37-1.76-.82,0-1.24.5-1.24,1.48v4.65h-1.9v-4.79c0-.98.25-1.76.75-2.33.52-.58,1.19-.87,2.03-.87.97,0,1.71.37,2.19,1.12l.47.79.47-.79c.49-.75,1.22-1.12,2.19-1.12.84,0,1.51.29,2.03.87.5.58.75,1.35.75,2.33v4.79Z"/></svg>',mail:'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" points="1.4,6.5 10,11 18.6,6.5"/><path d="M 1,4 1,16 19,16 19,4 1,4 Z M 18,15 2,15 2,5 18,5 18,15 Z"/></svg>',lock:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="13" height="10" fill="none" stroke="#000" x="3.5" y="8.5"/><path fill="none" stroke="#000" d="M6.5,8 L6.5,4.88 C6.5,3.01 8.07,1.5 10,1.5 C11.93,1.5 13.5,3.01 13.5,4.88 L13.5,8"/></svg>',location:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.01" d="M10,0.5 C6.41,0.5 3.5,3.39 3.5,6.98 C3.5,11.83 10,19 10,19 C10,19 16.5,11.83 16.5,6.98 C16.5,3.39 13.59,0.5 10,0.5 L10,0.5 Z"/><circle fill="none" stroke="#000" cx="10" cy="6.8" r="2.3"/></svg>',list:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="12" height="1" x="6" y="4"/><rect width="12" height="1" x="6" y="9"/><rect width="12" height="1" x="6" y="14"/><rect width="2" height="1" x="2" y="4"/><rect width="2" height="1" x="2" y="9"/><rect width="2" height="1" x="2" y="14"/></svg>',linkedin:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M5.77,17.89 L5.77,7.17 L2.21,7.17 L2.21,17.89 L5.77,17.89 L5.77,17.89 Z M3.99,5.71 C5.23,5.71 6.01,4.89 6.01,3.86 C5.99,2.8 5.24,2 4.02,2 C2.8,2 2,2.8 2,3.85 C2,4.88 2.77,5.7 3.97,5.7 L3.99,5.7 L3.99,5.71 L3.99,5.71 Z"/><path d="M7.75,17.89 L11.31,17.89 L11.31,11.9 C11.31,11.58 11.33,11.26 11.43,11.03 C11.69,10.39 12.27,9.73 13.26,9.73 C14.55,9.73 15.06,10.71 15.06,12.15 L15.06,17.89 L18.62,17.89 L18.62,11.74 C18.62,8.45 16.86,6.92 14.52,6.92 C12.6,6.92 11.75,7.99 11.28,8.73 L11.3,8.73 L11.3,7.17 L7.75,7.17 C7.79,8.17 7.75,17.89 7.75,17.89 L7.75,17.89 L7.75,17.89 Z"/></svg>',link:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="M10.625,12.375 L7.525,15.475 C6.825,16.175 5.925,16.175 5.225,15.475 L4.525,14.775 C3.825,14.074 3.825,13.175 4.525,12.475 L7.625,9.375"/><path fill="none" stroke="#000" stroke-width="1.1" d="M9.325,7.375 L12.425,4.275 C13.125,3.575 14.025,3.575 14.724,4.275 L15.425,4.975 C16.125,5.675 16.125,6.575 15.425,7.275 L12.325,10.375"/><path fill="none" stroke="#000" stroke-width="1.1" d="M7.925,11.875 L11.925,7.975"/></svg>',"link-external":'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" points="15 10.5 15 17 3 17 3 5 9.5 5"/><line fill="none" stroke="#000" x1="8.22" y1="11.79" x2="17.01" y2="2.99"/><polyline fill="none" stroke="#000" points="12.5 3 17 3 17 7.5"/></svg>',lifesaver:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" cx="10" cy="10" r="9"/><circle fill="none" stroke="#000" cx="10" cy="10" r="5"/><line fill="none" stroke="#000" stroke-width="1.1" x1="5.17" y1="2.39" x2="8.11" y2="5.33"/><line fill="none" stroke="#000" stroke-width="1.1" x1="5.33" y1="8.11" x2="2.39" y2="5.17"/><line fill="none" stroke="#000" stroke-width="1.1" x1="14.83" y1="17.61" x2="11.89" y2="14.67"/><line fill="none" stroke="#000" stroke-width="1.1" x1="14.67" y1="11.89" x2="17.61" y2="14.83"/><line fill="none" stroke="#000" stroke-width="1.1" x1="17.61" y1="5.17" x2="14.67" y2="8.11"/><line fill="none" stroke="#000" stroke-width="1.1" x1="11.89" y1="5.33" x2="14.83" y2="2.39"/><line fill="none" stroke="#000" stroke-width="1.1" x1="8.11" y1="14.67" x2="5.17" y2="17.61"/><line fill="none" stroke="#000" stroke-width="1.1" x1="2.39" y1="14.83" x2="5.33" y2="11.89"/></svg>',laptop:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="20" height="1" y="16"/><rect width="15" height="10" fill="none" stroke="#000" x="2.5" y="4.5"/></svg>',joomla:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M7.8,13.4l1.7-1.7L5.9,8c-0.6-0.5-0.6-1.5,0-2c0.6-0.6,1.4-0.6,2,0l1.7-1.7c-1-1-2.3-1.3-3.6-1C5.8,2.2,4.8,1.4,3.7,1.4 c-1.3,0-2.3,1-2.3,2.3c0,1.1,0.8,2,1.8,2.3c-0.4,1.3-0.1,2.8,1,3.8L7.8,13.4L7.8,13.4z"/><path d="M10.2,4.3c1-1,2.5-1.4,3.8-1c0.2-1.1,1.1-2,2.3-2c1.3,0,2.3,1,2.3,2.3c0,1.2-0.9,2.2-2,2.3c0.4,1.3,0,2.8-1,3.8L13.9,8 c0.6-0.5,0.6-1.5,0-2c-0.5-0.6-1.5-0.6-2,0L8.2,9.7L6.5,8"/><path d="M14.1,16.8c-1.3,0.4-2.8,0.1-3.8-1l1.7-1.7c0.6,0.6,1.5,0.6,2,0c0.5-0.6,0.6-1.5,0-2l-3.7-3.7L12,6.7l3.7,3.7 c1,1,1.3,2.4,1,3.6c1.1,0.2,2,1.1,2,2.3c0,1.3-1,2.3-2.3,2.3C15.2,18.6,14.3,17.8,14.1,16.8"/><path d="M13.2,12.2l-3.7,3.7c-1,1-2.4,1.3-3.6,1c-0.2,1-1.2,1.8-2.2,1.8c-1.3,0-2.3-1-2.3-2.3c0-1.1,0.8-2,1.8-2.3 c-0.3-1.3,0-2.7,1-3.7l1.7,1.7c-0.6,0.6-0.6,1.5,0,2c0.6,0.6,1.4,0.6,2,0l3.7-3.7"/></svg>',italic:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M12.63,5.48 L10.15,14.52 C10,15.08 10.37,15.25 11.92,15.3 L11.72,16 L6,16 L6.2,15.31 C7.78,15.26 8.19,15.09 8.34,14.53 L10.82,5.49 C10.97,4.92 10.63,4.76 9.09,4.71 L9.28,4 L15,4 L14.81,4.69 C13.23,4.75 12.78,4.91 12.63,5.48 L12.63,5.48 Z"/></svg>',instagram:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M13.55,1H6.46C3.45,1,1,3.44,1,6.44v7.12c0,3,2.45,5.44,5.46,5.44h7.08c3.02,0,5.46-2.44,5.46-5.44V6.44 C19.01,3.44,16.56,1,13.55,1z M17.5,14c0,1.93-1.57,3.5-3.5,3.5H6c-1.93,0-3.5-1.57-3.5-3.5V6c0-1.93,1.57-3.5,3.5-3.5h8 c1.93,0,3.5,1.57,3.5,3.5V14z"/><circle cx="14.87" cy="5.26" r="1.09"/><path d="M10.03,5.45c-2.55,0-4.63,2.06-4.63,4.6c0,2.55,2.07,4.61,4.63,4.61c2.56,0,4.63-2.061,4.63-4.61 C14.65,7.51,12.58,5.45,10.03,5.45L10.03,5.45L10.03,5.45z M10.08,13c-1.66,0-3-1.34-3-2.99c0-1.65,1.34-2.99,3-2.99s3,1.34,3,2.99 C13.08,11.66,11.74,13,10.08,13L10.08,13L10.08,13z"/></svg>',info:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M12.13,11.59 C11.97,12.84 10.35,14.12 9.1,14.16 C6.17,14.2 9.89,9.46 8.74,8.37 C9.3,8.16 10.62,7.83 10.62,8.81 C10.62,9.63 10.12,10.55 9.88,11.32 C8.66,15.16 12.13,11.15 12.14,11.18 C12.16,11.21 12.16,11.35 12.13,11.59 C12.08,11.95 12.16,11.35 12.13,11.59 L12.13,11.59 Z M11.56,5.67 C11.56,6.67 9.36,7.15 9.36,6.03 C9.36,5 11.56,4.54 11.56,5.67 L11.56,5.67 Z"/><circle fill="none" stroke="#000" stroke-width="1.1" cx="10" cy="10" r="9"/></svg>',image:'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="16.1" cy="6.1" r="1.1"/><rect width="19" height="15" fill="none" stroke="#000" x=".5" y="2.5"/><polyline fill="none" stroke="#000" stroke-width="1.01" points="4,13 8,9 13,14"/><polyline fill="none" stroke="#000" stroke-width="1.01" points="11,12 12.5,10.5 16,14"/></svg>',home:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon points="18.65 11.35 10 2.71 1.35 11.35 0.65 10.65 10 1.29 19.35 10.65"/><polygon points="15 4 18 4 18 7 17 7 17 5 15 5"/><polygon points="3 11 4 11 4 18 7 18 7 12 12 12 12 18 16 18 16 11 17 11 17 19 11 19 11 13 8 13 8 19 3 19"/></svg>',history:'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="#000" points="1 2 2 2 2 6 6 6 6 7 1 7 1 2"/><path fill="none" stroke="#000" stroke-width="1.1" d="M2.1,6.548 C3.391,3.29 6.746,1 10.5,1 C15.5,1 19.5,5 19.5,10 C19.5,15 15.5,19 10.5,19 C5.5,19 1.5,15 1.5,10"/><rect width="1" height="7" x="9" y="4"/><path fill="none" stroke="#000" stroke-width="1.1" d="M13.018,14.197 L9.445,10.625"/></svg>',heart:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.03" d="M10,4 C10,4 8.1,2 5.74,2 C3.38,2 1,3.55 1,6.73 C1,8.84 2.67,10.44 2.67,10.44 L10,18 L17.33,10.44 C17.33,10.44 19,8.84 19,6.73 C19,3.55 16.62,2 14.26,2 C11.9,2 10,4 10,4 L10,4 Z"/></svg>',hashtag:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M15.431,8 L15.661,7 L12.911,7 L13.831,3 L12.901,3 L11.98,7 L9.29,7 L10.21,3 L9.281,3 L8.361,7 L5.23,7 L5,8 L8.13,8 L7.21,12 L4.23,12 L4,13 L6.98,13 L6.061,17 L6.991,17 L7.911,13 L10.601,13 L9.681,17 L10.611,17 L11.531,13 L14.431,13 L14.661,12 L11.76,12 L12.681,8 L15.431,8 Z M10.831,12 L8.141,12 L9.061,8 L11.75,8 L10.831,12 Z"/></svg>',happy:'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="13" cy="7" r="1"/><circle cx="7" cy="7" r="1"/><circle fill="none" stroke="#000" cx="10" cy="10" r="8.5"/><path fill="none" stroke="#000" d="M14.6,11.4 C13.9,13.3 12.1,14.5 10,14.5 C7.9,14.5 6.1,13.3 5.4,11.4"/></svg>',grid:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="3" height="3" x="2" y="2"/><rect width="3" height="3" x="8" y="2"/><rect width="3" height="3" x="14" y="2"/><rect width="3" height="3" x="2" y="8"/><rect width="3" height="3" x="8" y="8"/><rect width="3" height="3" x="14" y="8"/><rect width="3" height="3" x="2" y="14"/><rect width="3" height="3" x="8" y="14"/><rect width="3" height="3" x="14" y="14"/></svg>',google:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M17.86,9.09 C18.46,12.12 17.14,16.05 13.81,17.56 C9.45,19.53 4.13,17.68 2.47,12.87 C0.68,7.68 4.22,2.42 9.5,2.03 C11.57,1.88 13.42,2.37 15.05,3.65 C15.22,3.78 15.37,3.93 15.61,4.14 C14.9,4.81 14.23,5.45 13.5,6.14 C12.27,5.08 10.84,4.72 9.28,4.98 C8.12,5.17 7.16,5.76 6.37,6.63 C4.88,8.27 4.62,10.86 5.76,12.82 C6.95,14.87 9.17,15.8 11.57,15.25 C13.27,14.87 14.76,13.33 14.89,11.75 L10.51,11.75 L10.51,9.09 L17.86,9.09 L17.86,9.09 Z"/></svg>',gitter:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="1.531" height="11.471" x="3.5" y="1"/><rect width="1.529" height="15.294" x="7.324" y="4.059"/><rect width="1.527" height="15.294" x="11.148" y="4.059"/><rect width="1.529" height="8.412" x="14.971" y="4.059"/></svg>',github:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M10,1 C5.03,1 1,5.03 1,10 C1,13.98 3.58,17.35 7.16,18.54 C7.61,18.62 7.77,18.34 7.77,18.11 C7.77,17.9 7.76,17.33 7.76,16.58 C5.26,17.12 4.73,15.37 4.73,15.37 C4.32,14.33 3.73,14.05 3.73,14.05 C2.91,13.5 3.79,13.5 3.79,13.5 C4.69,13.56 5.17,14.43 5.17,14.43 C5.97,15.8 7.28,15.41 7.79,15.18 C7.87,14.6 8.1,14.2 8.36,13.98 C6.36,13.75 4.26,12.98 4.26,9.53 C4.26,8.55 4.61,7.74 5.19,7.11 C5.1,6.88 4.79,5.97 5.28,4.73 C5.28,4.73 6.04,4.49 7.75,5.65 C8.47,5.45 9.24,5.35 10,5.35 C10.76,5.35 11.53,5.45 12.25,5.65 C13.97,4.48 14.72,4.73 14.72,4.73 C15.21,5.97 14.9,6.88 14.81,7.11 C15.39,7.74 15.73,8.54 15.73,9.53 C15.73,12.99 13.63,13.75 11.62,13.97 C11.94,14.25 12.23,14.8 12.23,15.64 C12.23,16.84 12.22,17.81 12.22,18.11 C12.22,18.35 12.38,18.63 12.84,18.54 C16.42,17.35 19,13.98 19,10 C19,5.03 14.97,1 10,1 L10,1 Z"/></svg>',"github-alt":'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M10,0.5 C4.75,0.5 0.5,4.76 0.5,10.01 C0.5,15.26 4.75,19.51 10,19.51 C15.24,19.51 19.5,15.26 19.5,10.01 C19.5,4.76 15.25,0.5 10,0.5 L10,0.5 Z M12.81,17.69 C12.81,17.69 12.81,17.7 12.79,17.69 C12.47,17.75 12.35,17.59 12.35,17.36 L12.35,16.17 C12.35,15.45 12.09,14.92 11.58,14.56 C12.2,14.51 12.77,14.39 13.26,14.21 C13.87,13.98 14.36,13.69 14.74,13.29 C15.42,12.59 15.76,11.55 15.76,10.17 C15.76,9.25 15.45,8.46 14.83,7.8 C15.1,7.08 15.07,6.29 14.75,5.44 L14.51,5.42 C14.34,5.4 14.06,5.46 13.67,5.61 C13.25,5.78 12.79,6.03 12.31,6.35 C11.55,6.16 10.81,6.05 10.09,6.05 C9.36,6.05 8.61,6.15 7.88,6.35 C7.28,5.96 6.75,5.68 6.26,5.54 C6.07,5.47 5.9,5.44 5.78,5.44 L5.42,5.44 C5.06,6.29 5.04,7.08 5.32,7.8 C4.7,8.46 4.4,9.25 4.4,10.17 C4.4,11.94 4.96,13.16 6.08,13.84 C6.53,14.13 7.05,14.32 7.69,14.43 C8.03,14.5 8.32,14.54 8.55,14.55 C8.07,14.89 7.82,15.42 7.82,16.16 L7.82,17.51 C7.8,17.69 7.7,17.8 7.51,17.8 C4.21,16.74 1.82,13.65 1.82,10.01 C1.82,5.5 5.49,1.83 10,1.83 C14.5,1.83 18.17,5.5 18.17,10.01 C18.18,13.53 15.94,16.54 12.81,17.69 L12.81,17.69 Z"/></svg>',"git-fork":'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" cx="6" cy="3" r="1.79"/><circle fill="none" stroke="#000" cx="14" cy="3" r="1.79"/><circle fill="none" stroke="#000" cx="10" cy="17" r="1.79"/><path fill="none" stroke="#000" d="m6,4.78v1.99c0,2.63,4,3.66,4,6.75,0,1.55.01,1.24.01,1.24,0-.18,0,.31,0-1.24,0-3.09,3.99-4.12,3.99-6.75v-1.99"/></svg>',"git-branch":'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="m13.5,8c0,2.41-1.57,2.87-3.44,3.25-1.47.29-3.56.81-3.56,3.75V5"/><circle fill="none" stroke="#000" cx="6.5" cy="3" r="1.79"/><circle fill="none" stroke="#000" cx="13.5" cy="6" r="1.79"/><circle fill="none" stroke="#000" cx="6.5" cy="17" r="1.79"/></svg>',future:'<svg width="20" height="20" viewBox="0 0 20 20"><polyline points="19 2 18 2 18 6 14 6 14 7 19 7 19 2"/><path fill="none" stroke="#000" stroke-width="1.1" d="M18,6.548 C16.709,3.29 13.354,1 9.6,1 C4.6,1 0.6,5 0.6,10 C0.6,15 4.6,19 9.6,19 C14.6,19 18.6,15 18.6,10"/><rect width="1" height="7" x="9" y="4"/><path fill="none" stroke="#000" stroke-width="1.1" d="M13.018,14.197 L9.445,10.625"/></svg>',foursquare:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M15.23,2 C15.96,2 16.4,2.41 16.5,2.86 C16.57,3.15 16.56,3.44 16.51,3.73 C16.46,4.04 14.86,11.72 14.75,12.03 C14.56,12.56 14.16,12.82 13.61,12.83 C13.03,12.84 11.09,12.51 10.69,13 C10.38,13.38 7.79,16.39 6.81,17.53 C6.61,17.76 6.4,17.96 6.08,17.99 C5.68,18.04 5.29,17.87 5.17,17.45 C5.12,17.28 5.1,17.09 5.1,16.91 C5.1,12.4 4.86,7.81 5.11,3.31 C5.17,2.5 5.81,2.12 6.53,2 L15.23,2 L15.23,2 Z M9.76,11.42 C9.94,11.19 10.17,11.1 10.45,11.1 L12.86,11.1 C13.12,11.1 13.31,10.94 13.36,10.69 C13.37,10.64 13.62,9.41 13.74,8.83 C13.81,8.52 13.53,8.28 13.27,8.28 C12.35,8.29 11.42,8.28 10.5,8.28 C9.84,8.28 9.83,7.69 9.82,7.21 C9.8,6.85 10.13,6.55 10.5,6.55 C11.59,6.56 12.67,6.55 13.76,6.55 C14.03,6.55 14.23,6.4 14.28,6.14 C14.34,5.87 14.67,4.29 14.67,4.29 C14.67,4.29 14.82,3.74 14.19,3.74 L7.34,3.74 C7,3.75 6.84,4.02 6.84,4.33 C6.84,7.58 6.85,14.95 6.85,14.99 C6.87,15 8.89,12.51 9.76,11.42 L9.76,11.42 Z"/></svg>',forward:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M2.47,13.11 C4.02,10.02 6.27,7.85 9.04,6.61 C9.48,6.41 10.27,6.13 11,5.91 L11,2 L18.89,9 L11,16 L11,12.13 C9.25,12.47 7.58,13.19 6.02,14.25 C3.03,16.28 1.63,18.54 1.63,18.54 C1.63,18.54 1.38,15.28 2.47,13.11 L2.47,13.11 Z M5.3,13.53 C6.92,12.4 9.04,11.4 12,10.92 L12,13.63 L17.36,9 L12,4.25 L12,6.8 C11.71,6.86 10.86,7.02 9.67,7.49 C6.79,8.65 4.58,10.96 3.49,13.08 C3.18,13.7 2.68,14.87 2.49,16 C3.28,15.05 4.4,14.15 5.3,13.53 L5.3,13.53 Z"/></svg>',folder:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon fill="none" stroke="#000" points="9.5 5.5 8.5 3.5 1.5 3.5 1.5 16.5 18.5 16.5 18.5 5.5"/></svg>',flickr:'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="5.5" cy="9.5" r="3.5"/><circle cx="14.5" cy="9.5" r="3.5"/></svg>',file:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="13" height="17" fill="none" stroke="#000" x="3.5" y="1.5"/></svg>',"file-text":'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="13" height="17" fill="none" stroke="#000" x="3.5" y="1.5"/><line fill="none" stroke="#000" x1="6" y1="12.5" x2="12" y2="12.5"/><line fill="none" stroke="#000" x1="6" y1="8.5" x2="14" y2="8.5"/><line fill="none" stroke="#000" x1="6" y1="6.5" x2="14" y2="6.5"/><line fill="none" stroke="#000" x1="6" y1="10.5" x2="14" y2="10.5"/></svg>',"file-pdf":'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="13" height="17" fill="none" stroke="#000" x="3.5" y="1.5"/><path d="M14.65 11.67c-.48.3-1.37-.19-1.79-.37a4.65 4.65 0 0 1 1.49.06c.35.1.36.28.3.31zm-6.3.06l.43-.79a14.7 14.7 0 0 0 .75-1.64 5.48 5.48 0 0 0 1.25 1.55l.2.15a16.36 16.36 0 0 0-2.63.73zM9.5 5.32c.2 0 .32.5.32.97a1.99 1.99 0 0 1-.23 1.04 5.05 5.05 0 0 1-.17-1.3s0-.71.08-.71zm-3.9 9a4.35 4.35 0 0 1 1.21-1.46l.24-.22a4.35 4.35 0 0 1-1.46 1.68zm9.23-3.3a2.05 2.05 0 0 0-1.32-.3 11.07 11.07 0 0 0-1.58.11 4.09 4.09 0 0 1-.74-.5 5.39 5.39 0 0 1-1.32-2.06 10.37 10.37 0 0 0 .28-2.62 1.83 1.83 0 0 0-.07-.25.57.57 0 0 0-.52-.4H9.4a.59.59 0 0 0-.6.38 6.95 6.95 0 0 0 .37 3.14c-.26.63-1 2.12-1 2.12-.3.58-.57 1.08-.82 1.5l-.8.44A3.11 3.11 0 0 0 5 14.16a.39.39 0 0 0 .15.42l.24.13c1.15.56 2.28-1.74 2.66-2.42a23.1 23.1 0 0 1 3.59-.85 4.56 4.56 0 0 0 2.91.8.5.5 0 0 0 .3-.21 1.1 1.1 0 0 0 .12-.75.84.84 0 0 0-.14-.25z"/></svg>',"file-edit":'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="M18.65,1.68 C18.41,1.45 18.109,1.33 17.81,1.33 C17.499,1.33 17.209,1.45 16.98,1.68 L8.92,9.76 L8,12.33 L10.55,11.41 L18.651,3.34 C19.12,2.87 19.12,2.15 18.65,1.68 L18.65,1.68 L18.65,1.68 Z"/><polyline fill="none" stroke="#000" points="16.5 8.482 16.5 18.5 3.5 18.5 3.5 1.5 14.211 1.5"/></svg>',facebook:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M11,10h2.6l0.4-3H11V5.3c0-0.9,0.2-1.5,1.5-1.5H14V1.1c-0.3,0-1-0.1-2.1-0.1C9.6,1,8,2.4,8,5v2H5.5v3H8v8h3V10z"/></svg>',eye:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" cx="10" cy="10" r="3.45"/><path fill="none" stroke="#000" d="m19.5,10c-2.4,3.66-5.26,7-9.5,7h0,0,0c-4.24,0-7.1-3.34-9.49-7C2.89,6.34,5.75,3,9.99,3h0,0,0c4.25,0,7.11,3.34,9.5,7Z"/></svg>',"eye-slash":'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="m7.56,7.56c.62-.62,1.49-1.01,2.44-1.01,1.91,0,3.45,1.54,3.45,3.45,0,.95-.39,1.82-1.01,2.44"/><path fill="none" stroke="#000" d="m19.5,10c-2.4,3.66-5.26,7-9.5,7h0,0,0c-4.24,0-7.1-3.34-9.49-7C2.89,6.34,5.75,3,9.99,3h0,0,0c4.25,0,7.11,3.34,9.5,7Z"/><line fill="none" stroke="#000" x1="2.5" y1="2.5" x2="17.5" y2="17.5"/></svg>',expand:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="M2.48,17.52l6.52-6.52"/><polyline fill="none" stroke="#000" points="6.97 17.52 2.48 17.52 2.48 13.03"/><path fill="none" stroke="#000" stroke-width="1.1" d="M17.52,2.48l-6.52,6.52"/><polyline fill="none" stroke="#000" points="13.03 2.48 17.52 2.48 17.52 6.97"/></svg>',etsy:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M8,4.26C8,4.07,8,4,8.31,4h4.46c.79,0,1.22.67,1.53,1.91l.25,1h.76c.14-2.82.26-4,.26-4S13.65,3,12.52,3H6.81L3.75,2.92v.84l1,.2c.73.11.9.27,1,1,0,0,.06,2,.06,5.17s-.06,5.14-.06,5.14c0,.59-.23.81-1,.94l-1,.2v.84l3.06-.1h5.11c1.15,0,3.82.1,3.82.1,0-.7.45-3.88.51-4.22h-.73l-.76,1.69a2.25,2.25,0,0,1-2.45,1.47H9.4c-1,0-1.44-.4-1.44-1.24V10.44s2.16,0,2.86.06c.55,0,.85.19,1.06,1l.23,1H13L12.9,9.94,13,7.41h-.85l-.28,1.13c-.16.74-.28.84-1,1-1,.1-2.89.09-2.89.09Z"/></svg>',dribbble:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.4" d="M1.3,8.9c0,0,5,0.1,8.6-1c1.4-0.4,2.6-0.9,4-1.9 c1.4-1.1,2.5-2.5,2.5-2.5"/><path fill="none" stroke="#000" stroke-width="1.4" d="M3.9,16.6c0,0,1.7-2.8,3.5-4.2 c1.8-1.3,4-2,5.7-2.2C16,10,19,10.6,19,10.6"/><path fill="none" stroke="#000" stroke-width="1.4" d="M6.9,1.6c0,0,3.3,4.6,4.2,6.8 c0.4,0.9,1.3,3.1,1.9,5.2c0.6,2,0.9,4.4,0.9,4.4"/><circle fill="none" stroke="#000" stroke-width="1.4" cx="10" cy="10" r="9"/></svg>',download:'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="10" y1="2.09" x2="10" y2="14.09"/><polyline fill="none" stroke="#000" points="6.16 10.62 10 14.46 13.84 10.62"/><line stroke="#000" x1="3.5" y1="17.5" x2="16.5" y2="17.5"/></svg>',discord:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M16.074,4.361a14.243,14.243,0,0,0-3.61-1.134,10.61,10.61,0,0,0-.463.96,13.219,13.219,0,0,0-4,0,10.138,10.138,0,0,0-.468-.96A14.206,14.206,0,0,0,3.919,4.364,15.146,15.146,0,0,0,1.324,14.5a14.435,14.435,0,0,0,4.428,2.269A10.982,10.982,0,0,0,6.7,15.21a9.294,9.294,0,0,1-1.494-.727c.125-.093.248-.19.366-.289a10.212,10.212,0,0,0,8.854,0c.119.1.242.2.366.289a9.274,9.274,0,0,1-1.5.728,10.8,10.8,0,0,0,.948,1.562,14.419,14.419,0,0,0,4.431-2.27A15.128,15.128,0,0,0,16.074,4.361Zm-8.981,8.1a1.7,1.7,0,0,1-1.573-1.79A1.689,1.689,0,0,1,7.093,8.881a1.679,1.679,0,0,1,1.573,1.791A1.687,1.687,0,0,1,7.093,12.462Zm5.814,0a1.7,1.7,0,0,1-1.573-1.79,1.689,1.689,0,0,1,1.573-1.791,1.679,1.679,0,0,1,1.573,1.791A1.688,1.688,0,0,1,12.907,12.462Z"/></svg>',desktop:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="1" height="2" x="8" y="15"/><rect width="1" height="2" x="11" y="15"/><rect width="10" height="1" x="5" y="16"/><rect width="17" height="11" fill="none" stroke="#000" x="1.5" y="3.5"/></svg>',database:'<svg width="20" height="20" viewBox="0 0 20 20"><ellipse fill="none" stroke="#000" cx="10" cy="4.64" rx="7.5" ry="3.14"/><path fill="none" stroke="#000" d="M17.5,8.11 C17.5,9.85 14.14,11.25 10,11.25 C5.86,11.25 2.5,9.84 2.5,8.11"/><path fill="none" stroke="#000" d="M17.5,11.25 C17.5,12.99 14.14,14.39 10,14.39 C5.86,14.39 2.5,12.98 2.5,11.25"/><path fill="none" stroke="#000" d="M17.49,4.64 L17.5,14.36 C17.5,16.1 14.14,17.5 10,17.5 C5.86,17.5 2.5,16.09 2.5,14.36 L2.5,4.64"/></svg>',crosshairs:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" cx="10" cy="10" r="7.5"/><line fill="none" stroke="#000" x1="10" x2="10" y2="8"/><line fill="none" stroke="#000" x1="10" y1="12" x2="10" y2="20"/><line fill="none" stroke="#000" y1="10" x2="8" y2="10"/><line fill="none" stroke="#000" x1="12" y1="10" x2="20" y2="10"/></svg>',"credit-card":'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="17" height="12" fill="none" stroke="#000" x="1.5" y="4.5"/><rect width="18" height="3" x="1" y="7"/></svg>',copy:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="12" height="16" fill="none" stroke="#000" x="3.5" y="2.5"/><polyline fill="none" stroke="#000" points="5 0.5 17.5 0.5 17.5 17"/></svg>',comments:'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" points="2 0.5 19.5 0.5 19.5 13"/><path d="M5,19.71 L5,15 L0,15 L0,2 L18,2 L18,15 L9.71,15 L5,19.71 L5,19.71 L5,19.71 Z M1,14 L6,14 L6,17.29 L9.29,14 L17,14 L17,3 L1,3 L1,14 L1,14 L1,14 Z"/></svg>',commenting:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon fill="none" stroke="#000" points="1.5,1.5 18.5,1.5 18.5,13.5 10.5,13.5 6.5,17.5 6.5,13.5 1.5,13.5"/><circle cx="10" cy="8" r="1"/><circle cx="6" cy="8" r="1"/><circle cx="14" cy="8" r="1"/></svg>',comment:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M6,18.71 L6,14 L1,14 L1,1 L19,1 L19,14 L10.71,14 L6,18.71 L6,18.71 Z M2,13 L7,13 L7,16.29 L10.29,13 L18,13 L18,2 L2,2 L2,13 L2,13 Z"/></svg>',cog:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" cx="9.997" cy="10" r="3.31"/><path fill="none" stroke="#000" d="M18.488,12.285 L16.205,16.237 C15.322,15.496 14.185,15.281 13.303,15.791 C12.428,16.289 12.047,17.373 12.246,18.5 L7.735,18.5 C7.938,17.374 7.553,16.299 6.684,15.791 C5.801,15.27 4.655,15.492 3.773,16.237 L1.5,12.285 C2.573,11.871 3.317,10.999 3.317,9.991 C3.305,8.98 2.573,8.121 1.5,7.716 L3.765,3.784 C4.645,4.516 5.794,4.738 6.687,4.232 C7.555,3.722 7.939,2.637 7.735,1.5 L12.263,1.5 C12.072,2.637 12.441,3.71 13.314,4.22 C14.206,4.73 15.343,4.516 16.225,3.794 L18.487,7.714 C17.404,8.117 16.661,8.988 16.67,10.009 C16.672,11.018 17.415,11.88 18.488,12.285 L18.488,12.285 Z"/></svg>',code:'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" stroke-width="1.01" points="13,4 19,10 13,16"/><polyline fill="none" stroke="#000" stroke-width="1.01" points="7,4 1,10 7,16"/></svg>',"cloud-upload":'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="M6.5,13.77h-2.75c-1.79,0-3.25-1.44-3.25-3.22,0-1.63,1.22-2.98,2.81-3.19.07-2.89,2.44-5.2,5.37-5.2,2.51,0,4.63,1.71,5.21,4.02.5-.22,1.04-.34,1.61-.34,2.21,0,4,1.77,4,3.96s-1.79,3.96-4,3.96h-3"/><path fill="none" stroke="#000" d="M9.51,9.34v9"/><polyline fill="none" stroke="#000" points="6.34 11.85 9.51 8.68 12.68 11.85"/></svg>',"cloud-download":'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="M6.5,13.28h-2.75c-1.79,0-3.25-1.44-3.25-3.22,0-1.63,1.22-2.98,2.8-3.19.08-2.89,2.45-5.2,5.38-5.2,2.51,0,4.63,1.71,5.21,4.02.5-.22,1.04-.34,1.61-.34,2.21,0,4,1.77,4,3.96s-1.79,3.96-4,3.96h-3"/><path fill="none" stroke="#000" d="M9.5,18.17v-10"/><polyline fill="none" stroke="#000" points="12.67 15.66 9.5 18.83 6.33 15.66"/></svg>',close:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.06" d="M16,16 L4,4"/><path fill="none" stroke="#000" stroke-width="1.06" d="M16,4 L4,16"/></svg>',"close-circle":'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="10" cy="10" r="9"/><line fill="none" stroke="#000" x1="13.18" y1="6.82" x2="6.82" y2="13.18"/><line fill="none" stroke="#000" x1="6.82" y1="6.82" x2="13.18" y2="13.18"/></svg>',clock:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="10" cy="10" r="9"/><rect width="1" height="7" x="9" y="4"/><path fill="none" stroke="#000" stroke-width="1.1" d="M13.018,14.197 L9.445,10.625"/></svg>',"chevron-up":'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" stroke-width="1.03" points="4 13 10 7 16 13"/></svg>',"chevron-right":'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" stroke-width="1.03" points="7 4 13 10 7 16"/></svg>',"chevron-left":'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" stroke-width="1.03" points="13 16 7 10 13 4"/></svg>',"chevron-down":'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" stroke-width="1.03" points="16 7 10 13 4 7"/></svg>',"chevron-double-right":'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" stroke-width="1.03" points="10 6 14 10 10 14"/><polyline fill="none" stroke="#000" stroke-width="1.03" points="6 6 10 10 6 14"/></svg>',"chevron-double-left":'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" stroke-width="1.03" points="10 14 6 10 10 6"/><polyline fill="none" stroke="#000" stroke-width="1.03" points="14 14 10 10 14 6"/></svg>',check:'<svg width="20" height="20" viewBox="0 0 20 20"><polyline fill="none" stroke="#000" stroke-width="1.1" points="4,10 8,15 17,4"/></svg>',cart:'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="7.3" cy="17.3" r="1.4"/><circle cx="13.3" cy="17.3" r="1.4"/><polyline fill="none" stroke="#000" points="0 2 3.2 4 5.3 12.5 16 12.5 18 6.5 8 6.5"/></svg>',camera:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="10" cy="10.8" r="3.8"/><path fill="none" stroke="#000" d="M1,4.5 C0.7,4.5 0.5,4.7 0.5,5 L0.5,17 C0.5,17.3 0.7,17.5 1,17.5 L19,17.5 C19.3,17.5 19.5,17.3 19.5,17 L19.5,5 C19.5,4.7 19.3,4.5 19,4.5 L13.5,4.5 L13.5,2.9 C13.5,2.6 13.3,2.5 13,2.5 L7,2.5 C6.7,2.5 6.5,2.6 6.5,2.9 L6.5,4.5 L1,4.5 L1,4.5 Z"/></svg>',calendar:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M 2,3 2,17 18,17 18,3 2,3 Z M 17,16 3,16 3,8 17,8 17,16 Z M 17,7 3,7 3,4 17,4 17,7 Z"/><rect width="1" height="3" x="6" y="2"/><rect width="1" height="3" x="13" y="2"/></svg>',bookmark:'<svg width="20" height="20" viewBox="0 0 20 20"><polygon fill="none" stroke="#000" points="5.5 1.5 15.5 1.5 15.5 17.5 10.5 12.5 5.5 17.5"/></svg>',bolt:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M4.74,20 L7.73,12 L3,12 L15.43,1 L12.32,9 L17.02,9 L4.74,20 L4.74,20 L4.74,20 Z M9.18,11 L7.1,16.39 L14.47,10 L10.86,10 L12.99,4.67 L5.61,11 L9.18,11 L9.18,11 L9.18,11 Z"/></svg>',bold:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M5,15.3 C5.66,15.3 5.9,15 5.9,14.53 L5.9,5.5 C5.9,4.92 5.56,4.7 5,4.7 L5,4 L8.95,4 C12.6,4 13.7,5.37 13.7,6.9 C13.7,7.87 13.14,9.17 10.86,9.59 L10.86,9.7 C13.25,9.86 14.29,11.28 14.3,12.54 C14.3,14.47 12.94,16 9,16 L5,16 L5,15.3 Z M9,9.3 C11.19,9.3 11.8,8.5 11.85,7 C11.85,5.65 11.3,4.8 9,4.8 L7.67,4.8 L7.67,9.3 L9,9.3 Z M9.185,15.22 C11.97,15 12.39,14 12.4,12.58 C12.4,11.15 11.39,10 9,10 L7.67,10 L7.67,15 L9.18,15 Z"/></svg>',bluesky:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M9.993,9.149c-.772-1.495-2.865-4.288-4.813-5.662-1.866-1.317-2.58-1.09-3.043-.878-.54.246-.637,1.075-.637,1.563s.265,4.003.444,4.587c.579,1.939,2.628,2.595,4.519,2.382.096-.014.193-.029.294-.039-.096.014-.198.029-.294.039-2.768.41-5.233,1.418-2.001,5.011,3.55,3.675,4.866-.786,5.541-3.053.675,2.262,1.452,6.564,5.474,3.053,3.024-3.053.83-4.601-1.939-5.011-.096-.01-.198-.024-.294-.039.101.014.198.024.294.039,1.89.212,3.945-.444,4.519-2.382.174-.588.444-4.099.444-4.587s-.096-1.317-.637-1.563c-.468-.212-1.177-.439-3.043.878-1.963,1.379-4.056,4.167-4.827,5.662h0Z"/></svg>',bell:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" stroke-width="1.1" d="M17,15.5 L3,15.5 C2.99,14.61 3.79,13.34 4.1,12.51 C4.58,11.3 4.72,10.35 5.19,7.01 C5.54,4.53 5.89,3.2 7.28,2.16 C8.13,1.56 9.37,1.5 9.81,1.5 L9.96,1.5 C9.96,1.5 11.62,1.41 12.67,2.17 C14.08,3.2 14.42,4.54 14.77,7.02 C15.26,10.35 15.4,11.31 15.87,12.52 C16.2,13.34 17.01,14.61 17,15.5 L17,15.5 Z"/><path fill="none" stroke="#000" d="M12.39,16 C12.39,17.37 11.35,18.43 9.91,18.43 C8.48,18.43 7.42,17.37 7.42,16"/></svg>',behance:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M9.5,10.6c-0.4-0.5-0.9-0.9-1.6-1.1c1.7-1,2.2-3.2,0.7-4.7C7.8,4,6.3,4,5.2,4C3.5,4,1.7,4,0,4v12c1.7,0,3.4,0,5.2,0 c1,0,2.1,0,3.1-0.5C10.2,14.6,10.5,12.3,9.5,10.6L9.5,10.6z M5.6,6.1c1.8,0,1.8,2.7-0.1,2.7c-1,0-2,0-2.9,0V6.1H5.6z M2.6,13.8v-3.1 c1.1,0,2.1,0,3.2,0c2.1,0,2.1,3.2,0.1,3.2L2.6,13.8z"/><path d="M19.9,10.9C19.7,9.2,18.7,7.6,17,7c-4.2-1.3-7.3,3.4-5.3,7.1c0.9,1.7,2.8,2.3,4.7,2.1c1.7-0.2,2.9-1.3,3.4-2.9h-2.2 c-0.4,1.3-2.4,1.5-3.5,0.6c-0.4-0.4-0.6-1.1-0.6-1.7H20C20,11.7,19.9,10.9,19.9,10.9z M13.5,10.6c0-1.6,2.3-2.7,3.5-1.4 c0.4,0.4,0.5,0.9,0.6,1.4H13.5L13.5,10.6z"/><rect width="5" height="1.4" x="13" y="4"/></svg>',ban:'<svg width="20" height="20" viewBox="0 0 20 20"><circle fill="none" stroke="#000" stroke-width="1.1" cx="10" cy="10" r="9"/><line fill="none" stroke="#000" stroke-width="1.1" x1="4" y1="3.5" x2="16" y2="16.5"/></svg>',bag:'<svg width="20" height="20" viewBox="0 0 20 20"><path fill="none" stroke="#000" d="M7.5,7.5V4A2.48,2.48,0,0,1,10,1.5,2.54,2.54,0,0,1,12.5,4V7.5"/><polygon fill="none" stroke="#000" points="16.5 7.5 3.5 7.5 2.5 18.5 17.5 18.5 16.5 7.5"/></svg>',"arrow-up":'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="10" y1="16.53" x2="10" y2="4.53"/><polyline fill="none" stroke="#000" points="13.84 8 10 4.17 6.16 8"/></svg>',"arrow-up-right":'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="4.5" y1="15.53" x2="16.5" y2="3.53"/><polyline fill="none" stroke="#000" points="16.5 9 16.5 3.5 11 3.5"/></svg>',"arrow-right":'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="3.47" y1="10" x2="15.47" y2="10"/><polyline fill="none" stroke="#000" points="11.98 13.84 15.82 10 11.98 6.16"/></svg>',"arrow-left":'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="16.53" y1="10" x2="4.53" y2="10"/><polyline fill="none" stroke="#000" points="8 6.16 4.18 10 8 13.84"/></svg>',"arrow-down":'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="10" y1="3.48" x2="10" y2="15.48"/><polyline fill="none" stroke="#000" points="6.16 12 10 15.84 13.84 12"/></svg>',"arrow-down-arrow-up":'<svg width="20" height="20" viewBox="0 0 20 20"><line fill="none" stroke="#000" x1="7" y1="3.38" x2="7" y2="15.38"/><polyline fill="none" stroke="#000" points="10.18 12.75 7 15.93 3.83 12.76"/><line fill="none" stroke="#000" x1="13" y1="16.62" x2="13" y2="4.62"/><polyline fill="none" stroke="#000" points="9.82 7.25 13 4.07 16.17 7.24"/></svg>',apple:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m17.23,6.93c-.1.08-1.95,1.12-1.95,3.43,0,2.67,2.35,3.62,2.42,3.64-.01.06-.37,1.29-1.24,2.55-.77,1.11-1.58,2.22-2.8,2.22s-1.54-.71-2.95-.71-1.87.73-2.99.73-1.9-1.03-2.8-2.29c-1.04-1.48-1.88-3.78-1.88-5.96,0-3.5,2.28-5.36,4.51-5.36,1.19,0,2.18.78,2.93.78s1.82-.83,3.17-.83c.51,0,2.36.05,3.57,1.79h0Zm-4.21-3.27c.56-.66.96-1.59.96-2.51,0-.13-.01-.26-.03-.36-.91.03-1.99.61-2.65,1.36-.51.58-.99,1.5-.99,2.44,0,.14.02.28.03.33.06.01.15.02.24.02.82,0,1.85-.55,2.44-1.28h0Z"/></svg>',android:'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m14.88,6.77l1.66-2.87c.09-.16.04-.37-.12-.46-.16-.09-.37-.04-.46.12l-1.68,2.91c-1.28-.59-2.73-.91-4.28-.91s-3,.33-4.28.91l-1.68-2.91c-.09-.16-.3-.22-.46-.12-.16.09-.22.3-.12.46l1.66,2.87C2.26,8.32.32,11.22,0,14.61h20c-.32-3.39-2.26-6.29-5.12-7.84h0Zm-9.47,5.03c-.46,0-.84-.38-.84-.84s.38-.84.84-.84.84.38.84.84c0,.46-.37.84-.84.84Zm9.18,0c-.46,0-.84-.38-.84-.84s.38-.84.84-.84.84.38.84.84c0,.46-.37.84-.84.84Z"/></svg>',"android-robot":'<svg width="20" height="20" viewBox="0 0 20 20"><path d="m17.61,7.96v4.64c-.06,1.48-2.17,1.48-2.23,0v-4.64c.06-1.48,2.17-1.48,2.23,0Z"/><path d="m4.62,7.96v4.64c-.06,1.48-2.17,1.48-2.23,0v-4.64c.06-1.48,2.17-1.48,2.23,0Z"/><path d="m12.78,2.85c-.11-.07-.23-.13-.34-.19.13-.23.65-1.17.79-1.42.07-.12-.05-.27-.18-.23-.04.01-.07.04-.09.08l-.79,1.43c-1.32-.6-2.98-.6-4.3,0-.13-.23-.65-1.18-.79-1.43-.04-.07-.14-.1-.21-.06-.08.04-.1.14-.06.21,0,0,.79,1.42.79,1.42-1.49.77-2.53,2.28-2.53,3.99-.02,0,9.93,0,9.93,0,.01-1.55-.87-2.98-2.19-3.8Zm-5.07,1.98c-.23,0-.41-.19-.41-.41.01-.27.21-.41.41-.41s.4.14.42.41c0,.22-.18.42-.41.41Zm4.58,0c-.23,0-.42-.19-.41-.41.01-.28.21-.41.41-.41s.4.14.41.41c0,.23-.19.41-.41.41Z"/><path d="m14.97,7.03v7.2c0,.66-.54,1.2-1.2,1.2h-.8v2.46c-.06,1.48-2.16,1.48-2.23,0,0,0,0-2.46,0-2.46h-1.48v2.46c0,.61-.5,1.11-1.11,1.11s-1.11-.5-1.11-1.11v-2.46h-.8c-.66,0-1.2-.54-1.2-1.2,0,0,0-7.2,0-7.2h9.93Z"/></svg>',album:'<svg width="20" height="20" viewBox="0 0 20 20"><rect width="10" height="1" x="5" y="2"/><rect width="14" height="1" x="3" y="4"/><rect width="17" height="11" fill="none" stroke="#000" x="1.5" y="6.5"/></svg>',"500px":'<svg width="20" height="20" viewBox="0 0 20 20"><path d="M9.624,11.866c-0.141,0.132,0.479,0.658,0.662,0.418c0.051-0.046,0.607-0.61,0.662-0.664c0,0,0.738,0.719,0.814,0.719 c0.1,0,0.207-0.055,0.322-0.17c0.27-0.269,0.135-0.416,0.066-0.495l-0.631-0.616l0.658-0.668c0.146-0.156,0.021-0.314-0.1-0.449 c-0.182-0.18-0.359-0.226-0.471-0.125l-0.656,0.654l-0.654-0.654c-0.033-0.034-0.08-0.045-0.124-0.045 c-0.079,0-0.191,0.068-0.307,0.181c-0.202,0.202-0.247,0.351-0.133,0.462l0.665,0.665L9.624,11.866z"/><path d="M11.066,2.884c-1.061,0-2.185,0.248-3.011,0.604c-0.087,0.034-0.141,0.106-0.15,0.205C7.893,3.784,7.919,3.909,7.982,4.066 c0.05,0.136,0.187,0.474,0.452,0.372c0.844-0.326,1.779-0.507,2.633-0.507c0.963,0,1.9,0.191,2.781,0.564 c0.695,0.292,1.357,0.719,2.078,1.34c0.051,0.044,0.105,0.068,0.164,0.068c0.143,0,0.273-0.137,0.389-0.271 c0.191-0.214,0.324-0.395,0.135-0.575c-0.686-0.654-1.436-1.138-2.363-1.533C13.24,3.097,12.168,2.884,11.066,2.884z"/><path d="M16.43,15.747c-0.092-0.028-0.242,0.05-0.309,0.119l0,0c-0.652,0.652-1.42,1.169-2.268,1.521 c-0.877,0.371-1.814,0.551-2.779,0.551c-0.961,0-1.896-0.189-2.775-0.564c-0.848-0.36-1.612-0.879-2.268-1.53 c-0.682-0.688-1.196-1.455-1.529-2.268c-0.325-0.799-0.471-1.643-0.471-1.643c-0.045-0.24-0.258-0.249-0.567-0.203 c-0.128,0.021-0.519,0.079-0.483,0.36v0.01c0.105,0.644,0.289,1.284,0.545,1.895c0.417,0.969,1.002,1.849,1.756,2.604 c0.757,0.754,1.636,1.34,2.604,1.757C8.901,18.785,9.97,19,11.088,19c1.104,0,2.186-0.215,3.188-0.645 c1.838-0.896,2.604-1.757,2.604-1.757c0.182-0.204,0.227-0.317-0.1-0.643C16.779,15.956,16.525,15.774,16.43,15.747z"/><path d="M5.633,13.287c0.293,0.71,0.723,1.341,1.262,1.882c0.54,0.54,1.172,0.971,1.882,1.264c0.731,0.303,1.509,0.461,2.298,0.461 c0.801,0,1.578-0.158,2.297-0.461c0.711-0.293,1.344-0.724,1.883-1.264c0.543-0.541,0.971-1.172,1.264-1.882 c0.314-0.721,0.463-1.5,0.463-2.298c0-0.79-0.148-1.569-0.463-2.289c-0.293-0.699-0.721-1.329-1.264-1.881 c-0.539-0.541-1.172-0.959-1.867-1.263c-0.721-0.303-1.5-0.461-2.299-0.461c-0.802,0-1.613,0.159-2.322,0.461 c-0.577,0.25-1.544,0.867-2.119,1.454v0.012V2.108h8.16C15.1,2.104,15.1,1.69,15.1,1.552C15.1,1.417,15.1,1,14.809,1H5.915 C5.676,1,5.527,1.192,5.527,1.384v6.84c0,0.214,0.273,0.372,0.529,0.428c0.5,0.105,0.614-0.056,0.737-0.224l0,0 c0.18-0.273,0.776-0.884,0.787-0.894c0.901-0.905,2.117-1.408,3.416-1.408c1.285,0,2.5,0.501,3.412,1.408 c0.914,0.914,1.408,2.122,1.408,3.405c0,1.288-0.508,2.496-1.408,3.405c-0.9,0.896-2.152,1.406-3.438,1.406 c-0.877,0-1.711-0.229-2.433-0.671v-4.158c0-0.553,0.237-1.151,0.643-1.614c0.462-0.519,1.094-0.799,1.782-0.799 c0.664,0,1.293,0.253,1.758,0.715c0.459,0.459,0.709,1.071,0.709,1.723c0,1.385-1.094,2.468-2.488,2.468 c-0.273,0-0.769-0.121-0.781-0.125c-0.281-0.087-0.405,0.306-0.438,0.436c-0.159,0.496,0.079,0.585,0.123,0.607 c0.452,0.137,0.743,0.157,1.129,0.157c1.973,0,3.572-1.6,3.572-3.57c0-1.964-1.6-3.552-3.572-3.552c-0.97,0-1.872,0.36-2.546,1.038 c-0.656,0.631-1.027,1.487-1.027,2.322v3.438v-0.011c-0.372-0.42-0.732-1.041-0.981-1.682c-0.102-0.248-0.315-0.202-0.607-0.113 c-0.135,0.035-0.519,0.157-0.44,0.439C5.372,12.799,5.577,13.164,5.633,13.287z"/></svg>'})}return typeof window<"u"&&window.UIkit&&window.UIkit.use(e),e});

!function(e,t){"object"==typeof exports&&"object"==typeof module?module.exports=t():"function"==typeof define&&define.amd?define(t):"object"==typeof exports?exports.acceptedlanguages=t():e.acceptedlanguages=t()}(this,function(){return function(e){function t(r){if(n[r])return n[r].exports;var a=n[r]={exports:{},id:r,loaded:!1};return e[r].call(a.exports,a,a.exports,t),a.loaded=!0,a.exports}var n={};return t.m=e,t.c=n,t.p="",t(0)}([function(e,t,n){"use strict";function r(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var n in e)Object.prototype.hasOwnProperty.call(e,n)&&(t[n]=e[n]);return t["default"]=e,t}Object.defineProperty(t,"__esModule",{value:!0});var a=n(1),u=r(a),o=n(2),c=r(o),l=n(4),g=r(l),i=n(5),f=r(i);t["default"]={lib:{util:u,user:c,page:g,relevant:f},current:g.getCurrentLanguage(),accepted:c.getAcceptedLanguages(),acceptedExpanded:u.expandLanguages(c.getAcceptedLanguages()),alternate:g.getAlternateLanguages(),alternateExpanded:u.expandLanguages(g.getAlternateLanguages()),relevant:f.getRelevantAlternateLanguages()},e.exports=t["default"]},function(e,t){"use strict";function n(e){var t={};return e.forEach(function(e){t[e]=e;var n=e.match(/^[a-zA-Z]+/)[0];n==e||t[n]||(t[n]=e)}),t}Object.defineProperty(t,"__esModule",{value:!0}),t.expandLanguages=n},function(e,t,n){"use strict";function r(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var n in e)Object.prototype.hasOwnProperty.call(e,n)&&(t[n]=e[n]);return t["default"]=e,t}function a(){var e=o.getRoot();return e.navigator?e.navigator.languages||[e.navigator.language||e.navigator.userLanguage]:[]}Object.defineProperty(t,"__esModule",{value:!0}),t.getAcceptedLanguages=a;var u=n(3),o=r(u)},function(e,t){"use strict";function n(){return a}function r(e){a=e}Object.defineProperty(t,"__esModule",{value:!0}),t.getRoot=n,t.setRoot=r;var a=window},function(e,t,n){"use strict";function r(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var n in e)Object.prototype.hasOwnProperty.call(e,n)&&(t[n]=e[n]);return t["default"]=e,t}function a(){var e=g.getRoot(),t=e.document.querySelector("html");return t.getAttribute("lang")}function u(){for(var e=g.getRoot(),t=e.document.querySelector("head").querySelectorAll('link[rel="alternate"]'),n=[],r=0;r<t.length;r++){var a=t.item(r),u=a.getAttribute("hreflang");u&&n.push(u)}return n}function o(e){var t=g.getRoot(),n=t.document.querySelector("head").querySelector('link[rel="alternate"][hreflang="'+e+'"]');return n}function c(e){var t=o(e);return t.getAttribute("href")}Object.defineProperty(t,"__esModule",{value:!0}),t.getCurrentLanguage=a,t.getAlternateLanguages=u,t.getLinkForLanguage=o,t.getHrefForLanguage=c;var l=n(3),g=r(l)},function(e,t,n){"use strict";function r(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var n in e)Object.prototype.hasOwnProperty.call(e,n)&&(t[n]=e[n]);return t["default"]=e,t}function a(){var e=o.expandLanguages(l.getAcceptedLanguages()),t=o.expandLanguages(i.getAlternateLanguages()),n=Object.keys(e),r=Object.keys(t),a=n.filter(function(e){return-1!==r.indexOf(e)}),u=a.map(function(e){return t[e]}),c={},g=u.filter(function(e){return c[e]?!1:(c[e]=!0,!0)});return g}Object.defineProperty(t,"__esModule",{value:!0}),t.getRelevantAlternateLanguages=a;var u=n(1),o=r(u),c=n(2),l=r(c),g=n(4),i=r(g)}])});
/**
 * Swiper 3.4.2
 * Most modern mobile touch slider and framework with hardware accelerated transitions
 *
 * http://www.idangero.us/swiper/
 *
 * Copyright 2017, Vladimir Kharlampidi
 * The iDangero.us
 * http://www.idangero.us/
 *
 * Licensed under MIT
 *
 * Released on: March 10, 2017
 */
(function () {
  'use strict';
  var $;

  /*===========================
  Swiper
  ===========================*/
  var Swiper = function (container, params) {
      if (!(this instanceof Swiper)) return new Swiper(container, params);


    var defaults = {
        direction: 'horizontal',
        touchEventsTarget: 'container',
        initialSlide: 0,
        speed: 300,
        // autoplay
        autoplay: false,
        autoplayDisableOnInteraction: true,
        autoplayStopOnLast: false,
        // To support iOS's swipe-to-go-back gesture (when being used in-app, with UIWebView).
        iOSEdgeSwipeDetection: false,
        iOSEdgeSwipeThreshold: 20,
        // Free mode
        freeMode: false,
        freeModeMomentum: true,
        freeModeMomentumRatio: 1,
        freeModeMomentumBounce: true,
        freeModeMomentumBounceRatio: 1,
        freeModeMomentumVelocityRatio: 1,
        freeModeMomentumMinimumVelocity: 0,
        freeModeMomentumMaximumVelocity: 0,
        freeModeSticky: false,
        freeModeMinimumVelocity: 0.02,
        // Autoheight
        autoHeight: false,
        // Set wrapper width
        setWrapperSize: false,
        // Virtual Translate
        virtualTranslate: false,
        // Effects
        effect: 'slide', // 'slide' or 'fade' or 'cube' or 'coverflow' or 'flip' or 'itunes'
        coverflow: {
            rotate: 50,
            depth: 100,
            modifier: 1,
            slideShadows: true
        },
        itunes: {
            stretch: 0,
            depth: 100,
            modifier: 1,
            slideShadows: true,
            itunes: null,
            scaleMultiplier: 0.001,
            scaleOffset: 1,
        },
        itunesTranslate: function () {

            var transform = s.translate;
            var center = s.isHorizontal() ? -transform + s.width / 2 : -transform + s.height / 2;
            var translate = s.params.itunes.depth;

            //Each slide offset from center
            for (var i = 0, length = s.slides.length; i < length; i++) {
                var slide = s.slides.eq(i);
                var slideSize = s.slidesSizesGrid[i];
                var slideOffset = slide[0].swiperSlideOffset;
                var offsetMultiplier = (center - slideOffset - slideSize / 2) / slideSize * s.params.itunes.modifier;

                var translateZ = -translate * Math.abs(offsetMultiplier);

                //Fix for ultra small values
                if (Math.abs(translateZ) < 0.001) translateZ = 0;

                // Fix hover in Safari
                // linear fit {0,1},{-114.856, 328.55/360},{-229.712, 302.16/360},{-344.569, 279.69/360}
                var scale = s.params.itunes.scaleMultiplier * translateZ + s.params.itunes.scaleOffset;
                var slideTransform = 'scale(' + scale + ') translateZ(0)';

                slide.transform(slideTransform);

                var zIndex = -Math.abs(Math.round(offsetMultiplier*10)) + 1;
                slide[0].style.zIndex = zIndex;
            }

            //Set correct perspective for IE10
            if (s.browser.ie) {
                var ws = s.wrapper[0].style;
                ws.perspectiveOrigin = center + 'px 50%';
            }
        },
        flip: {
            slideShadows : true,
            limitRotation: true
        },
        cube: {
            slideShadows: true,
            shadow: true,
            shadowOffset: 20,
            shadowScale: 0.94
        },
        fade: {
            crossFade: false
        },
        // Parallax
        parallax: false,
        // Zoom
        zoom: false,
        zoomMax: 3,
        zoomMin: 1,
        zoomToggle: true,
        // Scrollbar
        scrollbar: null,
        scrollbarHide: true,
        scrollbarDraggable: false,
        scrollbarSnapOnRelease: false,
        // Keyboard Mousewheel
        keyboardControl: false,
        mousewheelControl: false,
        mousewheelReleaseOnEdges: false,
        mousewheelInvert: false,
        mousewheelForceToAxis: false,
        mousewheelSensitivity: 1,
        mousewheelEventsTarged: 'container',
        // Hash Navigation
        hashnav: false,
        hashnavWatchState: false,
        // History
        history: false,
        // Commong Nav State
        replaceState: false,
        // Breakpoints
        breakpoints: undefined,
        // Slides grid
        spaceBetween: 0,
        slidesPerView: 1,
        slidesPerColumn: 1,
        slidesPerColumnFill: 'column',
        slidesPerGroup: 1,
        centeredSlides: false,
        slidesOffsetBefore: 0, // in px
        slidesOffsetAfter: 0, // in px
        // Round length
        roundLengths: false,
        // Touches
        touchRatio: 1,
        touchAngle: 45,
        simulateTouch: true,
        shortSwipes: true,
        longSwipes: true,
        longSwipesRatio: 0.5,
        longSwipesMs: 300,
        followFinger: true,
        onlyExternal: false,
        threshold: 0,
        touchMoveStopPropagation: true,
        touchReleaseOnEdges: false,
        // Unique Navigation Elements
        uniqueNavElements: true,
        // Pagination
        pagination: null,
        paginationElement: 'span',
        paginationClickable: false,
        paginationHide: false,
        paginationBulletRender: null,
        paginationProgressRender: null,
        paginationFractionRender: null,
        paginationCustomRender: null,
        paginationType: 'bullets', // 'bullets' or 'progress' or 'fraction' or 'custom'
        // Resistance
        resistance: true,
        resistanceRatio: 0.85,
        // Next/prev buttons
        nextButton: null,
        prevButton: null,
        // Progress
        watchSlidesProgress: false,
        watchSlidesVisibility: false,
        // Cursor
        grabCursor: false,
        // Clicks
        preventClicks: true,
        preventClicksPropagation: true,
        slideToClickedSlide: false,
        // Lazy Loading
        lazyLoading: false,
        lazyLoadingInPrevNext: false,
        lazyLoadingInPrevNextAmount: 1,
        lazyLoadingOnTransitionStart: false,
        // Images
        preloadImages: true,
        updateOnImagesReady: true,
        // loop
        loop: false,
        loopAdditionalSlides: 0,
        loopedSlides: null,
        // Control
        control: undefined,
        controlInverse: false,
        controlBy: 'slide', //or 'container'
        normalizeSlideIndex: true,
        // Swiping/no swiping
        allowSwipeToPrev: true,
        allowSwipeToNext: true,
        swipeHandler: null, //'.swipe-handler',
        noSwiping: true,
        noSwipingClass: 'swiper-no-swiping',
        // Passive Listeners
        passiveListeners: true,
        // NS
        containerModifierClass: 'swiper-container-', // NEW
        slideClass: 'swiper-slide',
        slideActiveClass: 'swiper-slide-active',
        slideDuplicateActiveClass: 'swiper-slide-duplicate-active',
        slideVisibleClass: 'swiper-slide-visible',
        slideDuplicateClass: 'swiper-slide-duplicate',
        slideNextClass: 'swiper-slide-next',
        slideDuplicateNextClass: 'swiper-slide-duplicate-next',
        slidePrevClass: 'swiper-slide-prev',
        slideDuplicatePrevClass: 'swiper-slide-duplicate-prev',
        wrapperClass: 'swiper-wrapper',
        bulletClass: 'swiper-pagination-bullet',
        bulletActiveClass: 'swiper-pagination-bullet-active',
        buttonDisabledClass: 'swiper-button-disabled',
        paginationCurrentClass: 'swiper-pagination-current',
        paginationTotalClass: 'swiper-pagination-total',
        paginationHiddenClass: 'swiper-pagination-hidden',
        paginationProgressbarClass: 'swiper-pagination-progressbar',
        paginationClickableClass: 'swiper-pagination-clickable', // NEW
        paginationModifierClass: 'swiper-pagination-', // NEW
        lazyLoadingClass: 'swiper-lazy',
        lazyStatusLoadingClass: 'swiper-lazy-loading',
        lazyStatusLoadedClass: 'swiper-lazy-loaded',
        lazyPreloaderClass: 'swiper-lazy-preloader',
        notificationClass: 'swiper-notification',
        preloaderClass: 'preloader',
        zoomContainerClass: 'swiper-zoom-container',

        // Observer
        observer: false,
        observeParents: false,
        // Accessibility
        a11y: false,
        prevSlideMessage: 'Previous slide',
        nextSlideMessage: 'Next slide',
        firstSlideMessage: 'This is the first slide',
        lastSlideMessage: 'This is the last slide',
        paginationBulletMessage: 'Go to slide {{index}}',
        // Callbacks
        runCallbacksOnInit: true
        /*
        Callbacks:
        onInit: function (swiper)
        onDestroy: function (swiper)
        onBeforeResize: function (swiper)
        onAfterResize: function (swiper)
        onClick: function (swiper, e)
        onTap: function (swiper, e)
        onDoubleTap: function (swiper, e)
        onSliderMove: function (swiper, e)
        onSlideChangeStart: function (swiper)
        onSlideChangeEnd: function (swiper)
        onTransitionStart: function (swiper)
        onTransitionEnd: function (swiper)
        onImagesReady: function (swiper)
        onProgress: function (swiper, progress)
        onTouchStart: function (swiper, e)
        onTouchMove: function (swiper, e)
        onTouchMoveOpposite: function (swiper, e)
        onTouchEnd: function (swiper, e)
        onReachBeginning: function (swiper)
        onReachEnd: function (swiper)
        onSetTransition: function (swiper, duration)
        onSetTranslate: function (swiper, translate)
        onAutoplayStart: function (swiper)
        onAutoplayStop: function (swiper),
        onLazyImageLoad: function (swiper, slide, image)
        onLazyImageReady: function (swiper, slide, image)
        onKeyPress: function (swiper, keyCode)
        */

    };
      var initialVirtualTranslate = params && params.virtualTranslate;

      params = params || {};
      var originalParams = {};
      for (var param in params) {
          if (typeof params[param] === 'object' && params[param] !== null && !(params[param].nodeType || params[param] === window || params[param] === document || (typeof Dom7 !== 'undefined' && params[param] instanceof Dom7) || (typeof jQuery !== 'undefined' && params[param] instanceof jQuery))) {
              originalParams[param] = {};
              for (var deepParam in params[param]) {
                  originalParams[param][deepParam] = params[param][deepParam];
              }
          }
          else {
              originalParams[param] = params[param];
          }
      }
      for (var def in defaults) {
          if (typeof params[def] === 'undefined') {
              params[def] = defaults[def];
          }
          else if (typeof params[def] === 'object') {
              for (var deepDef in defaults[def]) {
                  if (typeof params[def][deepDef] === 'undefined') {
                      params[def][deepDef] = defaults[def][deepDef];
                  }
              }
          }
      }

      // Swiper
      var s = this;

      // Params
      s.params = params;
      s.originalParams = originalParams;

      // Classname
      s.classNames = [];
      /*=========================
        Dom Library and plugins
        ===========================*/
      if (typeof $ !== 'undefined' && typeof Dom7 !== 'undefined'){
          $ = Dom7;
      }
      if (typeof $ === 'undefined') {
          if (typeof Dom7 === 'undefined') {
              $ = window.Dom7 || window.Zepto || window.jQuery;
          }
          else {
              $ = Dom7;
          }
          if (!$) return;
      }
      // Export it to Swiper instance
      s.$ = $;

      /*=========================
        Breakpoints
        ===========================*/
      s.currentBreakpoint = undefined;
      s.getActiveBreakpoint = function () {
          //Get breakpoint for window width
          if (!s.params.breakpoints) return false;
          var breakpoint = false;
          var points = [], point;
          for ( point in s.params.breakpoints ) {
              if (s.params.breakpoints.hasOwnProperty(point)) {
                  points.push(point);
              }
          }
          points.sort(function (a, b) {
              return parseInt(a, 10) > parseInt(b, 10);
          });
          for (var i = 0; i < points.length; i++) {
              point = points[i];
              if (point >= window.innerWidth && !breakpoint) {
                  breakpoint = point;
              }
          }
          return breakpoint || 'max';
      };
      s.setBreakpoint = function () {
          //Set breakpoint for window width and update parameters
          var breakpoint = s.getActiveBreakpoint();
          if (breakpoint && s.currentBreakpoint !== breakpoint) {
              var breakPointsParams = breakpoint in s.params.breakpoints ? s.params.breakpoints[breakpoint] : s.originalParams;
              var needsReLoop = s.params.loop && (breakPointsParams.slidesPerView !== s.params.slidesPerView);
              for ( var param in breakPointsParams ) {
                  s.params[param] = breakPointsParams[param];
              }
              s.currentBreakpoint = breakpoint;
              if(needsReLoop && s.destroyLoop) {
                  s.reLoop(true);
              }
          }
      };
      // Set breakpoint on load
      if (s.params.breakpoints) {
          s.setBreakpoint();
      }

      /*=========================
        Preparation - Define Container, Wrapper and Pagination
        ===========================*/
      s.container = $(container);
      if (s.container.length === 0) return;
      if (s.container.length > 1) {
          var swipers = [];
          s.container.each(function () {
              var container = this;
              swipers.push(new Swiper(this, params));
          });
          return swipers;
      }

      // Save instance in container HTML Element and in data
      s.container[0].swiper = s;
      s.container.data('swiper', s);

      s.classNames.push(s.params.containerModifierClass + s.params.direction);

      if (s.params.freeMode) {
          s.classNames.push(s.params.containerModifierClass + 'free-mode');
      }
      if (!s.support.flexbox) {
          s.classNames.push(s.params.containerModifierClass + 'no-flexbox');
          s.params.slidesPerColumn = 1;
      }
      if (s.params.autoHeight) {
          s.classNames.push(s.params.containerModifierClass + 'autoheight');
      }
      // Enable slides progress when required
      if (s.params.parallax || s.params.watchSlidesVisibility) {
          s.params.watchSlidesProgress = true;
      }
      // Max resistance when touchReleaseOnEdges
      if (s.params.touchReleaseOnEdges) {
          s.params.resistanceRatio = 0;
      }
      // Coverflow / 3D
      if (['cube', 'coverflow', 'flip', 'itunes'].indexOf(s.params.effect) >= 0) {
          if (s.support.transforms3d) {
              s.params.watchSlidesProgress = true;
              s.classNames.push(s.params.containerModifierClass + '3d');
          }
          else {
              s.params.effect = 'slide';
          }
      }
      if (s.params.effect !== 'slide') {
          s.classNames.push(s.params.containerModifierClass + s.params.effect);
      }
      if (s.params.effect === 'cube') {
          s.params.resistanceRatio = 0;
          s.params.slidesPerView = 1;
          s.params.slidesPerColumn = 1;
          s.params.slidesPerGroup = 1;
          s.params.centeredSlides = false;
          s.params.spaceBetween = 0;
          s.params.virtualTranslate = true;
      }
      if (s.params.effect === 'fade' || s.params.effect === 'flip') {
          s.params.slidesPerView = 1;
          s.params.slidesPerColumn = 1;
          s.params.slidesPerGroup = 1;
          s.params.watchSlidesProgress = true;
          s.params.spaceBetween = 0;
          if (typeof initialVirtualTranslate === 'undefined') {
              s.params.virtualTranslate = true;
          }
      }

      // Grab Cursor
      if (s.params.grabCursor && s.support.touch) {
          s.params.grabCursor = false;
      }

      // Wrapper
      s.wrapper = s.container.children('.' + s.params.wrapperClass);

      // Pagination
      if (s.params.pagination) {
          s.paginationContainer = $(s.params.pagination);
          if (s.params.uniqueNavElements && typeof s.params.pagination === 'string' && s.paginationContainer.length > 1 && s.container.find(s.params.pagination).length === 1) {
              s.paginationContainer = s.container.find(s.params.pagination);
          }

          if (s.params.paginationType === 'bullets' && s.params.paginationClickable) {
              s.paginationContainer.addClass(s.params.paginationModifierClass + 'clickable');
          }
          else {
              s.params.paginationClickable = false;
          }
          s.paginationContainer.addClass(s.params.paginationModifierClass + s.params.paginationType);
      }
      // Next/Prev Buttons
      if (s.params.nextButton || s.params.prevButton) {
          if (s.params.nextButton) {
              s.nextButton = $(s.params.nextButton);
              if (s.params.uniqueNavElements && typeof s.params.nextButton === 'string' && s.nextButton.length > 1 && s.container.find(s.params.nextButton).length === 1) {
                  s.nextButton = s.container.find(s.params.nextButton);
              }
          }
          if (s.params.prevButton) {
              s.prevButton = $(s.params.prevButton);
              if (s.params.uniqueNavElements && typeof s.params.prevButton === 'string' && s.prevButton.length > 1 && s.container.find(s.params.prevButton).length === 1) {
                  s.prevButton = s.container.find(s.params.prevButton);
              }
          }
      }

      // Is Horizontal
      s.isHorizontal = function () {
          return s.params.direction === 'horizontal';
      };
      // s.isH = isH;

      // RTL
      s.rtl = s.isHorizontal() && (s.container[0].dir.toLowerCase() === 'rtl' || s.container.css('direction') === 'rtl');
      if (s.rtl) {
          s.classNames.push(s.params.containerModifierClass + 'rtl');
      }

      // Wrong RTL support
      if (s.rtl) {
          s.wrongRTL = s.wrapper.css('display') === '-webkit-box';
      }

      // Columns
      if (s.params.slidesPerColumn > 1) {
          s.classNames.push(s.params.containerModifierClass + 'multirow');
      }

      // Check for Android
      if (s.device.android) {
          s.classNames.push(s.params.containerModifierClass + 'android');
      }

      // Add classes
      s.container.addClass(s.classNames.join(' '));

      // Translate
      s.translate = 0;

      // Progress
      s.progress = 0;

      // Velocity
      s.velocity = 0;

      /*=========================
        Locks, unlocks
        ===========================*/
      s.lockSwipeToNext = function () {
          s.params.allowSwipeToNext = false;
          if (s.params.allowSwipeToPrev === false && s.params.grabCursor) {
              s.unsetGrabCursor();
          }
      };
      s.lockSwipeToPrev = function () {
          s.params.allowSwipeToPrev = false;
          if (s.params.allowSwipeToNext === false && s.params.grabCursor) {
              s.unsetGrabCursor();
          }
      };
      s.lockSwipes = function () {
          s.params.allowSwipeToNext = s.params.allowSwipeToPrev = false;
          if (s.params.grabCursor) s.unsetGrabCursor();
      };
      s.unlockSwipeToNext = function () {
          s.params.allowSwipeToNext = true;
          if (s.params.allowSwipeToPrev === true && s.params.grabCursor) {
              s.setGrabCursor();
          }
      };
      s.unlockSwipeToPrev = function () {
          s.params.allowSwipeToPrev = true;
          if (s.params.allowSwipeToNext === true && s.params.grabCursor) {
              s.setGrabCursor();
          }
      };
      s.unlockSwipes = function () {
          s.params.allowSwipeToNext = s.params.allowSwipeToPrev = true;
          if (s.params.grabCursor) s.setGrabCursor();
      };

      /*=========================
        Round helper
        ===========================*/
      function round(a) {
          return Math.floor(a);
      }
      /*=========================
        Set grab cursor
        ===========================*/
      s.setGrabCursor = function(moving) {
          s.container[0].style.cursor = 'move';
          s.container[0].style.cursor = moving ? '-webkit-grabbing' : '-webkit-grab';
          s.container[0].style.cursor = moving ? '-moz-grabbin' : '-moz-grab';
          s.container[0].style.cursor = moving ? 'grabbing': 'grab';
      };
      s.unsetGrabCursor = function () {
          s.container[0].style.cursor = '';
      };
      if (s.params.grabCursor) {
          s.setGrabCursor();
      }
      /*=========================
        Update on Images Ready
        ===========================*/
      s.imagesToLoad = [];
      s.imagesLoaded = 0;

      s.loadImage = function (imgElement, src, srcset, sizes, checkForComplete, callback) {
          var image;
          function onReady () {
              if (callback) callback();
          }
          if (!imgElement.complete || !checkForComplete) {
              if (src) {
                  image = new window.Image();
                  image.onload = onReady;
                  image.onerror = onReady;
                  if (sizes) {
                      image.sizes = sizes;
                  }
                  if (srcset) {
                      image.srcset = srcset;
                  }
                  if (src) {
                      image.src = src;
                  }
              } else {
                  onReady();
              }

          } else {//image already loaded...
              onReady();
          }
      };
      s.preloadImages = function () {
          s.imagesToLoad = s.container.find('img');
          function _onReady() {
              if (typeof s === 'undefined' || s === null || !s) return;
              if (s.imagesLoaded !== undefined) s.imagesLoaded++;
              if (s.imagesLoaded === s.imagesToLoad.length) {
                  if (s.params.updateOnImagesReady) s.update();
                  s.emit('onImagesReady', s);
              }
          }
          for (var i = 0; i < s.imagesToLoad.length; i++) {
              s.loadImage(s.imagesToLoad[i], (s.imagesToLoad[i].currentSrc || s.imagesToLoad[i].getAttribute('src')), (s.imagesToLoad[i].srcset || s.imagesToLoad[i].getAttribute('srcset')), s.imagesToLoad[i].sizes || s.imagesToLoad[i].getAttribute('sizes'), true, _onReady);
          }
      };

      /*=========================
        Autoplay
        ===========================*/
      s.autoplayTimeoutId = undefined;
      s.autoplaying = false;
      s.autoplayPaused = false;
      function autoplay() {
          var autoplayDelay = s.params.autoplay;
          var activeSlide = s.slides.eq(s.activeIndex);
          if (activeSlide.attr('data-swiper-autoplay')) {
              autoplayDelay = activeSlide.attr('data-swiper-autoplay') || s.params.autoplay;
          }
          s.autoplayTimeoutId = setTimeout(function () {
              if (s.params.loop) {
                  s.fixLoop();
                  s._slideNext();
                  s.emit('onAutoplay', s);
              }
              else {
                  if (!s.isEnd) {
                      s._slideNext();
                      s.emit('onAutoplay', s);
                  }
                  else {
                      if (!params.autoplayStopOnLast) {
                          s._slideTo(0);
                          s.emit('onAutoplay', s);
                      }
                      else {
                          s.stopAutoplay();
                      }
                  }
              }
          }, autoplayDelay);
      }
      s.startAutoplay = function () {
          if (typeof s.autoplayTimeoutId !== 'undefined') return false;
          if (!s.params.autoplay) return false;
          if (s.autoplaying) return false;
          s.autoplaying = true;
          s.emit('onAutoplayStart', s);
          autoplay();
      };
      s.stopAutoplay = function (internal) {
          if (!s.autoplayTimeoutId) return;
          if (s.autoplayTimeoutId) clearTimeout(s.autoplayTimeoutId);
          s.autoplaying = false;
          s.autoplayTimeoutId = undefined;
          s.emit('onAutoplayStop', s);
      };
      s.pauseAutoplay = function (speed) {
          if (s.autoplayPaused) return;
          if (s.autoplayTimeoutId) clearTimeout(s.autoplayTimeoutId);
          s.autoplayPaused = true;
          if (speed === 0) {
              s.autoplayPaused = false;
              autoplay();
          }
          else {
              s.wrapper.transitionEnd(function () {
                  if (!s) return;
                  s.autoplayPaused = false;
                  if (!s.autoplaying) {
                      s.stopAutoplay();
                  }
                  else {
                      autoplay();
                  }
              });
          }
      };
      /*=========================
        Min/Max Translate
        ===========================*/
      s.minTranslate = function () {
          return (-s.snapGrid[0]);
      };
      s.maxTranslate = function () {
          return (-s.snapGrid[s.snapGrid.length - 1]);
      };
      /*=========================
        Slider/slides sizes
        ===========================*/
      s.updateAutoHeight = function () {
          var activeSlides = [];
          var newHeight = 0;
          var i;

          // Find slides currently in view
          if(s.params.slidesPerView !== 'auto' && s.params.slidesPerView > 1) {
              for (i = 0; i < Math.ceil(s.params.slidesPerView); i++) {
                  var index = s.activeIndex + i;
                  if(index > s.slides.length) break;
                  activeSlides.push(s.slides.eq(index)[0]);
              }
          } else {
              activeSlides.push(s.slides.eq(s.activeIndex)[0]);
          }

          // Find new height from heighest slide in view
          for (i = 0; i < activeSlides.length; i++) {
              if (typeof activeSlides[i] !== 'undefined') {
                  var height = activeSlides[i].offsetHeight;
                  newHeight = height > newHeight ? height : newHeight;
              }
          }

          // Update Height
          if (newHeight) s.wrapper.css('height', newHeight + 'px');
      };
      s.updateContainerSize = function () {
          var width, height;
          if (typeof s.params.width !== 'undefined') {
              width = s.params.width;
          }
          else {
              width = s.container[0].clientWidth;
          }
          if (typeof s.params.height !== 'undefined') {
              height = s.params.height;
          }
          else {
              height = s.container[0].clientHeight;
          }
          if (width === 0 && s.isHorizontal() || height === 0 && !s.isHorizontal()) {
              return;
          }

          //Subtract paddings
          width = width - parseInt(s.container.css('padding-left'), 10) - parseInt(s.container.css('padding-right'), 10);
          height = height - parseInt(s.container.css('padding-top'), 10) - parseInt(s.container.css('padding-bottom'), 10);

          // Store values
          s.width = width;
          s.height = height;
          s.size = s.isHorizontal() ? s.width : s.height;
      };

      s.updateSlidesSize = function () {
          s.slides = s.wrapper.children('.' + s.params.slideClass);
          s.snapGrid = [];
          s.slidesGrid = [];
          s.slidesSizesGrid = [];

          var spaceBetween = s.params.spaceBetween,
              slidePosition = -s.params.slidesOffsetBefore,
              i,
              prevSlideSize = 0,
              index = 0;
          if (typeof s.size === 'undefined') return;
          if (typeof spaceBetween === 'string' && spaceBetween.indexOf('%') >= 0) {
              spaceBetween = parseFloat(spaceBetween.replace('%', '')) / 100 * s.size;
          }

          s.virtualSize = -spaceBetween;
          // reset margins
          if (s.rtl) s.slides.css({marginLeft: '', marginTop: ''});
          else s.slides.css({marginRight: '', marginBottom: ''});

          var slidesNumberEvenToRows;
          if (s.params.slidesPerColumn > 1) {
              if (Math.floor(s.slides.length / s.params.slidesPerColumn) === s.slides.length / s.params.slidesPerColumn) {
                  slidesNumberEvenToRows = s.slides.length;
              }
              else {
                  slidesNumberEvenToRows = Math.ceil(s.slides.length / s.params.slidesPerColumn) * s.params.slidesPerColumn;
              }
              if (s.params.slidesPerView !== 'auto' && s.params.slidesPerColumnFill === 'row') {
                  slidesNumberEvenToRows = Math.max(slidesNumberEvenToRows, s.params.slidesPerView * s.params.slidesPerColumn);
              }
          }

          // Calc slides
          var slideSize;
          var slidesPerColumn = s.params.slidesPerColumn;
          var slidesPerRow = slidesNumberEvenToRows / slidesPerColumn;
          var numFullColumns = slidesPerRow - (s.params.slidesPerColumn * slidesPerRow - s.slides.length);
          for (i = 0; i < s.slides.length; i++) {
              slideSize = 0;
              var slide = s.slides.eq(i);
              if (s.params.slidesPerColumn > 1) {
                  // Set slides order
                  var newSlideOrderIndex;
                  var column, row;
                  if (s.params.slidesPerColumnFill === 'column') {
                      column = Math.floor(i / slidesPerColumn);
                      row = i - column * slidesPerColumn;
                      if (column > numFullColumns || (column === numFullColumns && row === slidesPerColumn-1)) {
                          if (++row >= slidesPerColumn) {
                              row = 0;
                              column++;
                          }
                      }
                      newSlideOrderIndex = column + row * slidesNumberEvenToRows / slidesPerColumn;
                      slide
                          .css({
                              '-webkit-box-ordinal-group': newSlideOrderIndex,
                              '-moz-box-ordinal-group': newSlideOrderIndex,
                              '-ms-flex-order': newSlideOrderIndex,
                              '-webkit-order': newSlideOrderIndex,
                              'order': newSlideOrderIndex
                          });
                  }
                  else {
                      row = Math.floor(i / slidesPerRow);
                      column = i - row * slidesPerRow;
                  }
                  slide
                      .css(
                          'margin-' + (s.isHorizontal() ? 'top' : 'left'),
                          (row !== 0 && s.params.spaceBetween) && (s.params.spaceBetween + 'px')
                      )
                      .attr('data-swiper-column', column)
                      .attr('data-swiper-row', row);

              }
              if (slide.css('display') === 'none') continue;
              if (s.params.slidesPerView === 'auto') {
                  slideSize = s.isHorizontal() ? slide.outerWidth(true) : slide.outerHeight(true);
                  if (s.params.roundLengths) slideSize = round(slideSize);
              }
              else {
                  slideSize = (s.size - (s.params.slidesPerView - 1) * spaceBetween) / s.params.slidesPerView;
                  if (s.params.roundLengths) slideSize = round(slideSize);

                  if (s.isHorizontal()) {
                      s.slides[i].style.width = slideSize + 'px';
                  }
                  else {
                      s.slides[i].style.height = slideSize + 'px';
                  }
              }
              s.slides[i].swiperSlideSize = slideSize;
              s.slidesSizesGrid.push(slideSize);


              if (s.params.centeredSlides) {
                  slidePosition = slidePosition + slideSize / 2 + prevSlideSize / 2 + spaceBetween;
                  if(prevSlideSize === 0 && i !== 0) slidePosition = slidePosition - s.size / 2 - spaceBetween;
                  if (i === 0) slidePosition = slidePosition - s.size / 2 - spaceBetween;
                  if (Math.abs(slidePosition) < 1 / 1000) slidePosition = 0;
                  if ((index) % s.params.slidesPerGroup === 0) s.snapGrid.push(slidePosition);
                  s.slidesGrid.push(slidePosition);
              }
              else {
                  if ((index) % s.params.slidesPerGroup === 0) s.snapGrid.push(slidePosition);
                  s.slidesGrid.push(slidePosition);
                  slidePosition = slidePosition + slideSize + spaceBetween;
              }

              s.virtualSize += slideSize + spaceBetween;

              prevSlideSize = slideSize;

              index ++;
          }
          s.virtualSize = Math.max(s.virtualSize, s.size) + s.params.slidesOffsetAfter;
          var newSlidesGrid;

          if (
              s.rtl && s.wrongRTL && (s.params.effect === 'slide' || s.params.effect === 'coverflow' || s.params.effect === 'itunes')) {
              s.wrapper.css({width: s.virtualSize + s.params.spaceBetween + 'px'});
          }
          if (!s.support.flexbox || s.params.setWrapperSize) {
              if (s.isHorizontal()) s.wrapper.css({width: s.virtualSize + s.params.spaceBetween + 'px'});
              else s.wrapper.css({height: s.virtualSize + s.params.spaceBetween + 'px'});
          }

          if (s.params.slidesPerColumn > 1) {
              s.virtualSize = (slideSize + s.params.spaceBetween) * slidesNumberEvenToRows;
              s.virtualSize = Math.ceil(s.virtualSize / s.params.slidesPerColumn) - s.params.spaceBetween;
              if (s.isHorizontal()) s.wrapper.css({width: s.virtualSize + s.params.spaceBetween + 'px'});
              else s.wrapper.css({height: s.virtualSize + s.params.spaceBetween + 'px'});
              if (s.params.centeredSlides) {
                  newSlidesGrid = [];
                  for (i = 0; i < s.snapGrid.length; i++) {
                      if (s.snapGrid[i] < s.virtualSize + s.snapGrid[0]) newSlidesGrid.push(s.snapGrid[i]);
                  }
                  s.snapGrid = newSlidesGrid;
              }
          }

          // Remove last grid elements depending on width
          if (!s.params.centeredSlides) {
              newSlidesGrid = [];
              for (i = 0; i < s.snapGrid.length; i++) {
                  if (s.snapGrid[i] <= s.virtualSize - s.size) {
                      newSlidesGrid.push(s.snapGrid[i]);
                  }
              }
              s.snapGrid = newSlidesGrid;
              if (Math.floor(s.virtualSize - s.size) - Math.floor(s.snapGrid[s.snapGrid.length - 1]) > 1) {
                  s.snapGrid.push(s.virtualSize - s.size);
              }
          }
          if (s.snapGrid.length === 0) s.snapGrid = [0];

          if (s.params.spaceBetween !== 0) {
              if (s.isHorizontal()) {
                  if (s.rtl) s.slides.css({marginLeft: spaceBetween + 'px'});
                  else s.slides.css({marginRight: spaceBetween + 'px'});
              }
              else s.slides.css({marginBottom: spaceBetween + 'px'});
          }
          if (s.params.watchSlidesProgress) {
              s.updateSlidesOffset();
          }
      };
      s.updateSlidesOffset = function () {
          for (var i = 0; i < s.slides.length; i++) {
              s.slides[i].swiperSlideOffset = s.isHorizontal() ? s.slides[i].offsetLeft : s.slides[i].offsetTop;
          }
      };

      /*=========================
        Dynamic Slides Per View
        ===========================*/
      s.currentSlidesPerView = function () {
          var spv = 1, i, j;
          if (s.params.centeredSlides) {
              var size = s.slides[s.activeIndex].swiperSlideSize;
              var breakLoop;
              for (i = s.activeIndex + 1; i < s.slides.length; i++) {
                  if (s.slides[i] && !breakLoop) {
                      size += s.slides[i].swiperSlideSize;
                      spv ++;
                      if (size > s.size) breakLoop = true;
                  }
              }
              for (j = s.activeIndex - 1; j >= 0; j--) {
                  if (s.slides[j] && !breakLoop) {
                      size += s.slides[j].swiperSlideSize;
                      spv ++;
                      if (size > s.size) breakLoop = true;
                  }
              }
          }
          else {
              for (i = s.activeIndex + 1; i < s.slides.length; i++) {
                  if (s.slidesGrid[i] - s.slidesGrid[s.activeIndex] < s.size) {
                      spv++;
                  }
              }
          }
          return spv;
      };
      /*=========================
        Slider/slides progress
        ===========================*/
      s.updateSlidesProgress = function (translate) {
          if (typeof translate === 'undefined') {
              translate = s.translate || 0;
          }
          if (s.slides.length === 0) return;
          if (typeof s.slides[0].swiperSlideOffset === 'undefined') s.updateSlidesOffset();

          var offsetCenter = -translate;
          if (s.rtl) offsetCenter = translate;

          // Visible Slides
          s.slides.removeClass(s.params.slideVisibleClass);
          for (var i = 0; i < s.slides.length; i++) {
              var slide = s.slides[i];
              var slideProgress = (offsetCenter + (s.params.centeredSlides ? s.minTranslate() : 0) - slide.swiperSlideOffset) / (slide.swiperSlideSize + s.params.spaceBetween);
              if (s.params.watchSlidesVisibility) {
                  var slideBefore = -(offsetCenter - slide.swiperSlideOffset);
                  var slideAfter = slideBefore + s.slidesSizesGrid[i];
                  var isVisible =
                      (slideBefore >= 0 && slideBefore < s.size) ||
                      (slideAfter > 0 && slideAfter <= s.size) ||
                      (slideBefore <= 0 && slideAfter >= s.size);
                  if (isVisible) {
                      s.slides.eq(i).addClass(s.params.slideVisibleClass);
                  }
              }
              slide.progress = s.rtl ? -slideProgress : slideProgress;
          }
      };
      s.updateProgress = function (translate) {
          if (typeof translate === 'undefined') {
              translate = s.translate || 0;
          }
          var translatesDiff = s.maxTranslate() - s.minTranslate();
          var wasBeginning = s.isBeginning;
          var wasEnd = s.isEnd;
          if (translatesDiff === 0) {
              s.progress = 0;
              s.isBeginning = s.isEnd = true;
          }
          else {
              s.progress = (translate - s.minTranslate()) / (translatesDiff);
              s.isBeginning = s.progress <= 0;
              s.isEnd = s.progress >= 1;
          }
          if (s.isBeginning && !wasBeginning) s.emit('onReachBeginning', s);
          if (s.isEnd && !wasEnd) s.emit('onReachEnd', s);

          if (s.params.watchSlidesProgress) s.updateSlidesProgress(translate);
          s.emit('onProgress', s, s.progress);
      };
      s.updateActiveIndex = function () {
          var translate = s.rtl ? s.translate : -s.translate;
          var newActiveIndex, i, snapIndex;
          for (i = 0; i < s.slidesGrid.length; i ++) {
              if (typeof s.slidesGrid[i + 1] !== 'undefined') {
                  if (translate >= s.slidesGrid[i] && translate < s.slidesGrid[i + 1] - (s.slidesGrid[i + 1] - s.slidesGrid[i]) / 2) {
                      newActiveIndex = i;
                  }
                  else if (translate >= s.slidesGrid[i] && translate < s.slidesGrid[i + 1]) {
                      newActiveIndex = i + 1;
                  }
              }
              else {
                  if (translate >= s.slidesGrid[i]) {
                      newActiveIndex = i;
                  }
              }
          }
          // Normalize slideIndex
          if(s.params.normalizeSlideIndex){
              if (newActiveIndex < 0 || typeof newActiveIndex === 'undefined') newActiveIndex = 0;
          }
          // for (i = 0; i < s.slidesGrid.length; i++) {
              // if (- translate >= s.slidesGrid[i]) {
                  // newActiveIndex = i;
              // }
          // }
          snapIndex = Math.floor(newActiveIndex / s.params.slidesPerGroup);
          if (snapIndex >= s.snapGrid.length) snapIndex = s.snapGrid.length - 1;

          if (newActiveIndex === s.activeIndex) {
              return;
          }
          s.snapIndex = snapIndex;
          s.previousIndex = s.activeIndex;
          s.activeIndex = newActiveIndex;
          s.updateClasses();
          s.updateRealIndex();
      };
      s.updateRealIndex = function(){
          s.realIndex = parseInt(s.slides.eq(s.activeIndex).attr('data-swiper-slide-index') || s.activeIndex, 10);
      };

      /*=========================
        Classes
        ===========================*/
      s.updateClasses = function () {
          s.slides.removeClass(s.params.slideActiveClass + ' ' + s.params.slideNextClass + ' ' + s.params.slidePrevClass + ' ' + s.params.slideDuplicateActiveClass + ' ' + s.params.slideDuplicateNextClass + ' ' + s.params.slideDuplicatePrevClass);
          var activeSlide = s.slides.eq(s.activeIndex);
          // Active classes
          activeSlide.addClass(s.params.slideActiveClass);
          if (params.loop) {
              // Duplicate to all looped slides
              if (activeSlide.hasClass(s.params.slideDuplicateClass)) {
                  s.wrapper.children('.' + s.params.slideClass + ':not(.' + s.params.slideDuplicateClass + ')[data-swiper-slide-index="' + s.realIndex + '"]').addClass(s.params.slideDuplicateActiveClass);
              }
              else {
                  s.wrapper.children('.' + s.params.slideClass + '.' + s.params.slideDuplicateClass + '[data-swiper-slide-index="' + s.realIndex + '"]').addClass(s.params.slideDuplicateActiveClass);
              }
          }
          // Next Slide
          var nextSlide = activeSlide.next('.' + s.params.slideClass).addClass(s.params.slideNextClass);
          if (s.params.loop && nextSlide.length === 0) {
              nextSlide = s.slides.eq(0);
              nextSlide.addClass(s.params.slideNextClass);
          }
          // Prev Slide
          var prevSlide = activeSlide.prev('.' + s.params.slideClass).addClass(s.params.slidePrevClass);
          if (s.params.loop && prevSlide.length === 0) {
              prevSlide = s.slides.eq(-1);
              prevSlide.addClass(s.params.slidePrevClass);
          }
          if (params.loop) {
              // Duplicate to all looped slides
              if (nextSlide.hasClass(s.params.slideDuplicateClass)) {
                  s.wrapper.children('.' + s.params.slideClass + ':not(.' + s.params.slideDuplicateClass + ')[data-swiper-slide-index="' + nextSlide.attr('data-swiper-slide-index') + '"]').addClass(s.params.slideDuplicateNextClass);
              }
              else {
                  s.wrapper.children('.' + s.params.slideClass + '.' + s.params.slideDuplicateClass + '[data-swiper-slide-index="' + nextSlide.attr('data-swiper-slide-index') + '"]').addClass(s.params.slideDuplicateNextClass);
              }
              if (prevSlide.hasClass(s.params.slideDuplicateClass)) {
                  s.wrapper.children('.' + s.params.slideClass + ':not(.' + s.params.slideDuplicateClass + ')[data-swiper-slide-index="' + prevSlide.attr('data-swiper-slide-index') + '"]').addClass(s.params.slideDuplicatePrevClass);
              }
              else {
                  s.wrapper.children('.' + s.params.slideClass + '.' + s.params.slideDuplicateClass + '[data-swiper-slide-index="' + prevSlide.attr('data-swiper-slide-index') + '"]').addClass(s.params.slideDuplicatePrevClass);
              }
          }

          // Pagination
          if (s.paginationContainer && s.paginationContainer.length > 0) {
              // Current/Total
              var current,
                  total = s.params.loop ? Math.ceil((s.slides.length - s.loopedSlides * 2) / s.params.slidesPerGroup) : s.snapGrid.length;
              if (s.params.loop) {
                  current = Math.ceil((s.activeIndex - s.loopedSlides)/s.params.slidesPerGroup);
                  if (current > s.slides.length - 1 - s.loopedSlides * 2) {
                      current = current - (s.slides.length - s.loopedSlides * 2);
                  }
                  if (current > total - 1) current = current - total;
                  if (current < 0 && s.params.paginationType !== 'bullets') current = total + current;
              }
              else {
                  if (typeof s.snapIndex !== 'undefined') {
                      current = s.snapIndex;
                  }
                  else {
                      current = s.activeIndex || 0;
                  }
              }
              // Types
              if (s.params.paginationType === 'bullets' && s.bullets && s.bullets.length > 0) {
                  s.bullets.removeClass(s.params.bulletActiveClass);
                  if (s.paginationContainer.length > 1) {
                      s.bullets.each(function () {
                          if ($(this).index() === current) $(this).addClass(s.params.bulletActiveClass);
                      });
                  }
                  else {
                      s.bullets.eq(current).addClass(s.params.bulletActiveClass);
                  }
              }
              if (s.params.paginationType === 'fraction') {
                  s.paginationContainer.find('.' + s.params.paginationCurrentClass).text(current + 1);
                  s.paginationContainer.find('.' + s.params.paginationTotalClass).text(total);
              }
              if (s.params.paginationType === 'progress') {
                  var scale = (current + 1) / total,
                      scaleX = scale,
                      scaleY = 1;
                  if (!s.isHorizontal()) {
                      scaleY = scale;
                      scaleX = 1;
                  }
                  s.paginationContainer.find('.' + s.params.paginationProgressbarClass).transform('translate3d(0,0,0) scaleX(' + scaleX + ') scaleY(' + scaleY + ')').transition(s.params.speed);
              }
              if (s.params.paginationType === 'custom' && s.params.paginationCustomRender) {
                  s.paginationContainer.html(s.params.paginationCustomRender(s, current + 1, total));
                  s.emit('onPaginationRendered', s, s.paginationContainer[0]);
              }
          }

          // Next/active buttons
          if (!s.params.loop) {
              if (s.params.prevButton && s.prevButton && s.prevButton.length > 0) {
                  if (s.isBeginning) {
                      s.prevButton.addClass(s.params.buttonDisabledClass);
                      if (s.params.a11y && s.a11y) s.a11y.disable(s.prevButton);
                  }
                  else {
                      s.prevButton.removeClass(s.params.buttonDisabledClass);
                      if (s.params.a11y && s.a11y) s.a11y.enable(s.prevButton);
                  }
              }
              if (s.params.nextButton && s.nextButton && s.nextButton.length > 0) {
                  if (s.isEnd) {
                      s.nextButton.addClass(s.params.buttonDisabledClass);
                      if (s.params.a11y && s.a11y) s.a11y.disable(s.nextButton);
                  }
                  else {
                      s.nextButton.removeClass(s.params.buttonDisabledClass);
                      if (s.params.a11y && s.a11y) s.a11y.enable(s.nextButton);
                  }
              }
          }
      };

      /*=========================
        Pagination
        ===========================*/
      s.updatePagination = function () {
          if (!s.params.pagination) return;
          if (s.paginationContainer && s.paginationContainer.length > 0) {
              var paginationHTML = '';
              if (s.params.paginationType === 'bullets') {
                  var numberOfBullets = s.params.loop ? Math.ceil((s.slides.length - s.loopedSlides * 2) / s.params.slidesPerGroup) : s.snapGrid.length;
                  for (var i = 0; i < numberOfBullets; i++) {
                      if (s.params.paginationBulletRender) {
                          paginationHTML += s.params.paginationBulletRender(s, i, s.params.bulletClass);
                      }
                      else {
                          paginationHTML += '<' + s.params.paginationElement+' class="' + s.params.bulletClass + '"></' + s.params.paginationElement + '>';
                      }
                  }
                  s.paginationContainer.html(paginationHTML);
                  s.bullets = s.paginationContainer.find('.' + s.params.bulletClass);
                  if (s.params.paginationClickable && s.params.a11y && s.a11y) {
                      s.a11y.initPagination();
                  }
              }
              if (s.params.paginationType === 'fraction') {
                  if (s.params.paginationFractionRender) {
                      paginationHTML = s.params.paginationFractionRender(s, s.params.paginationCurrentClass, s.params.paginationTotalClass);
                  }
                  else {
                      paginationHTML =
                          '<span class="' + s.params.paginationCurrentClass + '"></span>' +
                          ' / ' +
                          '<span class="' + s.params.paginationTotalClass+'"></span>';
                  }
                  s.paginationContainer.html(paginationHTML);
              }
              if (s.params.paginationType === 'progress') {
                  if (s.params.paginationProgressRender) {
                      paginationHTML = s.params.paginationProgressRender(s, s.params.paginationProgressbarClass);
                  }
                  else {
                      paginationHTML = '<span class="' + s.params.paginationProgressbarClass + '"></span>';
                  }
                  s.paginationContainer.html(paginationHTML);
              }
              if (s.params.paginationType !== 'custom') {
                  s.emit('onPaginationRendered', s, s.paginationContainer[0]);
              }
          }
      };
      /*=========================
        Common update method
        ===========================*/
      s.update = function (updateTranslate) {
          if (!s) return;
          s.updateContainerSize();
          s.updateSlidesSize();
          s.updateProgress();
          s.updatePagination();
          s.updateClasses();
          if (s.params.scrollbar && s.scrollbar) {
              s.scrollbar.set();
          }
          var newTranslate;
          function forceSetTranslate() {
              var translate = s.rtl ? -s.translate : s.translate;
              newTranslate = Math.min(Math.max(s.translate, s.maxTranslate()), s.minTranslate());
              s.setWrapperTranslate(newTranslate);
              s.updateActiveIndex();
              s.updateClasses();
          }
          if (updateTranslate) {
              var translated;
              if (s.controller && s.controller.spline) {
                  s.controller.spline = undefined;
              }
              if (s.params.freeMode) {
                  forceSetTranslate();
                  if (s.params.autoHeight) {
                      s.updateAutoHeight();
                  }
              }
              else {
                  if ((s.params.slidesPerView === 'auto' || s.params.slidesPerView > 1) && s.isEnd && !s.params.centeredSlides) {
                      translated = s.slideTo(s.slides.length - 1, 0, false, true);
                  }
                  else {
                      translated = s.slideTo(s.activeIndex, 0, false, true);
                  }
                  if (!translated) {
                      forceSetTranslate();
                  }
              }
          }
          else if (s.params.autoHeight) {
              s.updateAutoHeight();
          }
      };

      /*=========================
        Resize Handler
        ===========================*/
      s.onResize = function (forceUpdatePagination) {
          if (s.params.onBeforeResize) s.params.onBeforeResize(s);
          //Breakpoints
          if (s.params.breakpoints) {
              s.setBreakpoint();
          }

          // Disable locks on resize
          var allowSwipeToPrev = s.params.allowSwipeToPrev;
          var allowSwipeToNext = s.params.allowSwipeToNext;
          s.params.allowSwipeToPrev = s.params.allowSwipeToNext = true;

          s.updateContainerSize();
          s.updateSlidesSize();
          if (s.params.slidesPerView === 'auto' || s.params.freeMode || forceUpdatePagination) s.updatePagination();
          if (s.params.scrollbar && s.scrollbar) {
              s.scrollbar.set();
          }
          if (s.controller && s.controller.spline) {
              s.controller.spline = undefined;
          }
          var slideChangedBySlideTo = false;
          if (s.params.freeMode) {
              var newTranslate = Math.min(Math.max(s.translate, s.maxTranslate()), s.minTranslate());
              s.setWrapperTranslate(newTranslate);
              s.updateActiveIndex();
              s.updateClasses();

              if (s.params.autoHeight) {
                  s.updateAutoHeight();
              }
          }
          else {
              s.updateClasses();
              if ((s.params.slidesPerView === 'auto' || s.params.slidesPerView > 1) && s.isEnd && !s.params.centeredSlides) {
                  slideChangedBySlideTo = s.slideTo(s.slides.length - 1, 0, false, true);
              }
              else {
                  slideChangedBySlideTo = s.slideTo(s.activeIndex, 0, false, true);
              }
          }
          if (s.params.lazyLoading && !slideChangedBySlideTo && s.lazy) {
              s.lazy.load();
          }
          // Return locks after resize
          s.params.allowSwipeToPrev = allowSwipeToPrev;
          s.params.allowSwipeToNext = allowSwipeToNext;
          if (s.params.onAfterResize) s.params.onAfterResize(s);
      };

      /*=========================
        Events
        ===========================*/

      //Define Touch Events
      s.touchEventsDesktop = {start: 'mousedown', move: 'mousemove', end: 'mouseup'};
      if (window.navigator.pointerEnabled) s.touchEventsDesktop = {start: 'pointerdown', move: 'pointermove', end: 'pointerup'};
      else if (window.navigator.msPointerEnabled) s.touchEventsDesktop = {start: 'MSPointerDown', move: 'MSPointerMove', end: 'MSPointerUp'};
      s.touchEvents = {
          start : s.support.touch || !s.params.simulateTouch  ? 'touchstart' : s.touchEventsDesktop.start,
          move : s.support.touch || !s.params.simulateTouch ? 'touchmove' : s.touchEventsDesktop.move,
          end : s.support.touch || !s.params.simulateTouch ? 'touchend' : s.touchEventsDesktop.end
      };


      // WP8 Touch Events Fix
      if (window.navigator.pointerEnabled || window.navigator.msPointerEnabled) {
          (s.params.touchEventsTarget === 'container' ? s.container : s.wrapper).addClass('swiper-wp8-' + s.params.direction);
      }

      // Attach/detach events
      s.initEvents = function (detach) {
          var actionDom = detach ? 'off' : 'on';
          var action = detach ? 'removeEventListener' : 'addEventListener';
          var touchEventsTarget = s.params.touchEventsTarget === 'container' ? s.container[0] : s.wrapper[0];
          var target = s.support.touch ? touchEventsTarget : document;

          var moveCapture = s.params.nested ? true : false;

          //Touch Events
          if (s.browser.ie) {
              touchEventsTarget[action](s.touchEvents.start, s.onTouchStart, false);
              target[action](s.touchEvents.move, s.onTouchMove, moveCapture);
              target[action](s.touchEvents.end, s.onTouchEnd, false);
          }
          else {
              if (s.support.touch) {
                  var passiveListener = s.touchEvents.start === 'touchstart' && s.support.passiveListener && s.params.passiveListeners ? {passive: true, capture: false} : false;
                  touchEventsTarget[action](s.touchEvents.start, s.onTouchStart, passiveListener);
                  touchEventsTarget[action](s.touchEvents.move, s.onTouchMove, moveCapture);
                  touchEventsTarget[action](s.touchEvents.end, s.onTouchEnd, passiveListener);
              }
              if ((params.simulateTouch && !s.device.ios && !s.device.android) || (params.simulateTouch && !s.support.touch && s.device.ios)) {
                  touchEventsTarget[action]('mousedown', s.onTouchStart, false);
                  document[action]('mousemove', s.onTouchMove, moveCapture);
                  document[action]('mouseup', s.onTouchEnd, false);
              }
          }
          window[action]('resize', s.onResize);

          // Next, Prev, Index
          if (s.params.nextButton && s.nextButton && s.nextButton.length > 0) {
              s.nextButton[actionDom]('click', s.onClickNext);
              if (s.params.a11y && s.a11y) s.nextButton[actionDom]('keydown', s.a11y.onEnterKey);
          }
          if (s.params.prevButton && s.prevButton && s.prevButton.length > 0) {
              s.prevButton[actionDom]('click', s.onClickPrev);
              if (s.params.a11y && s.a11y) s.prevButton[actionDom]('keydown', s.a11y.onEnterKey);
          }
          if (s.params.pagination && s.params.paginationClickable) {
              s.paginationContainer[actionDom]('click', '.' + s.params.bulletClass, s.onClickIndex);
              if (s.params.a11y && s.a11y) s.paginationContainer[actionDom]('keydown', '.' + s.params.bulletClass, s.a11y.onEnterKey);
          }

          // Prevent Links Clicks
          if (s.params.preventClicks || s.params.preventClicksPropagation) touchEventsTarget[action]('click', s.preventClicks, true);
      };
      s.attachEvents = function () {
          s.initEvents();
      };
      s.detachEvents = function () {
          s.initEvents(true);
      };

      /*=========================
        Handle Clicks
        ===========================*/
      // Prevent Clicks
      s.allowClick = true;
      s.preventClicks = function (e) {
          if (!s.allowClick) {
              if (s.params.preventClicks) e.preventDefault();
              if (s.params.preventClicksPropagation && s.animating) {
                  e.stopPropagation();
                  e.stopImmediatePropagation();
              }
          }
      };
      // Clicks
      s.onClickNext = function (e) {
          e.preventDefault();
          if (s.isEnd && !s.params.loop) return;
          s.slideNext();
      };
      s.onClickPrev = function (e) {
          e.preventDefault();
          if (s.isBeginning && !s.params.loop) return;
          s.slidePrev();
      };
      s.onClickIndex = function (e) {
          e.preventDefault();
          var index = $(this).index() * s.params.slidesPerGroup;
          if (s.params.loop) index = index + s.loopedSlides;
          s.slideTo(index);
      };

      /*=========================
        Handle Touches
        ===========================*/
      function findElementInEvent(e, selector) {
          var el = $(e.target);
          if (!el.is(selector)) {
              if (typeof selector === 'string') {
                  el = el.parents(selector);
              }
              else if (selector.nodeType) {
                  var found;
                  el.parents().each(function (index, _el) {
                      if (_el === selector) found = selector;
                  });
                  if (!found) return undefined;
                  else return selector;
              }
          }
          if (el.length === 0) {
              return undefined;
          }
          return el[0];
      }
      s.updateClickedSlide = function (e) {
          var slide = findElementInEvent(e, '.' + s.params.slideClass);
          var slideFound = false;
          if (slide) {
              for (var i = 0; i < s.slides.length; i++) {
                  if (s.slides[i] === slide) slideFound = true;
              }
          }

          if (slide && slideFound) {
              s.clickedSlide = slide;
              s.clickedIndex = $(slide).index();
          }
          else {
              s.clickedSlide = undefined;
              s.clickedIndex = undefined;
              return;
          }
          if (s.params.slideToClickedSlide && s.clickedIndex !== undefined && s.clickedIndex !== s.activeIndex) {
              var slideToIndex = s.clickedIndex,
                  realIndex,
                  duplicatedSlides,
                  slidesPerView = s.params.slidesPerView === 'auto' ? s.currentSlidesPerView() : s.params.slidesPerView;
              if (s.params.loop) {
                  if (s.animating) return;
                  realIndex = parseInt($(s.clickedSlide).attr('data-swiper-slide-index'), 10);
                  if (s.params.centeredSlides) {
                      if ((slideToIndex < s.loopedSlides - slidesPerView/2) || (slideToIndex > s.slides.length - s.loopedSlides + slidesPerView/2)) {
                          s.fixLoop();
                          slideToIndex = s.wrapper.children('.' + s.params.slideClass + '[data-swiper-slide-index="' + realIndex + '"]:not(.' + s.params.slideDuplicateClass + ')').eq(0).index();
                          setTimeout(function () {
                              s.slideTo(slideToIndex);
                          }, 0);
                      }
                      else {
                          s.slideTo(slideToIndex);
                      }
                  }
                  else {
                      if (slideToIndex > s.slides.length - slidesPerView) {
                          s.fixLoop();
                          slideToIndex = s.wrapper.children('.' + s.params.slideClass + '[data-swiper-slide-index="' + realIndex + '"]:not(.' + s.params.slideDuplicateClass + ')').eq(0).index();
                          setTimeout(function () {
                              s.slideTo(slideToIndex);
                          }, 0);
                      }
                      else {
                          s.slideTo(slideToIndex);
                      }
                  }
              }
              else {
                  s.slideTo(slideToIndex);
              }
          }
      };

      var isTouched,
          isMoved,
          allowTouchCallbacks,
          touchStartTime,
          isScrolling,
          currentTranslate,
          startTranslate,
          allowThresholdMove,
          // Form elements to match
          formElements = 'input, select, textarea, button, video',
          // Last click time
          lastClickTime = Date.now(), clickTimeout,
          //Velocities
          velocities = [],
          allowMomentumBounce;

      // Animating Flag
      s.animating = false;

      // Touches information
      s.touches = {
          startX: 0,
          startY: 0,
          currentX: 0,
          currentY: 0,
          diff: 0
      };

      // Touch handlers
      var isTouchEvent, startMoving;
      s.onTouchStart = function (e) {
          if (e.originalEvent) e = e.originalEvent;
          isTouchEvent = e.type === 'touchstart';
          if (!isTouchEvent && 'which' in e && e.which === 3) return;
          if (s.params.noSwiping && findElementInEvent(e, '.' + s.params.noSwipingClass)) {
              s.allowClick = true;
              return;
          }
          if (s.params.swipeHandler) {
              if (!findElementInEvent(e, s.params.swipeHandler)) return;
          }

          var startX = s.touches.currentX = e.type === 'touchstart' ? e.targetTouches[0].pageX : e.pageX;
          var startY = s.touches.currentY = e.type === 'touchstart' ? e.targetTouches[0].pageY : e.pageY;

          // Do NOT start if iOS edge swipe is detected. Otherwise iOS app (UIWebView) cannot swipe-to-go-back anymore
          if(s.device.ios && s.params.iOSEdgeSwipeDetection && startX <= s.params.iOSEdgeSwipeThreshold) {
              return;
          }

          isTouched = true;
          isMoved = false;
          allowTouchCallbacks = true;
          isScrolling = undefined;
          startMoving = undefined;
          s.touches.startX = startX;
          s.touches.startY = startY;
          touchStartTime = Date.now();
          s.allowClick = true;
          s.updateContainerSize();
          s.swipeDirection = undefined;
          if (s.params.threshold > 0) allowThresholdMove = false;
          if (e.type !== 'touchstart') {
              var preventDefault = true;
              if ($(e.target).is(formElements)) preventDefault = false;
              if (document.activeElement && $(document.activeElement).is(formElements)) {
                  document.activeElement.blur();
              }
              if (preventDefault) {
                  e.preventDefault();
              }
          }
          s.emit('onTouchStart', s, e);
      };

      s.onTouchMove = function (e) {
          if (e.originalEvent) e = e.originalEvent;
          if (isTouchEvent && e.type === 'mousemove') return;
          if (e.preventedByNestedSwiper) {
              s.touches.startX = e.type === 'touchmove' ? e.targetTouches[0].pageX : e.pageX;
              s.touches.startY = e.type === 'touchmove' ? e.targetTouches[0].pageY : e.pageY;
              return;
          }
          if (s.params.onlyExternal) {
              // isMoved = true;
              s.allowClick = false;
              if (isTouched) {
                  s.touches.startX = s.touches.currentX = e.type === 'touchmove' ? e.targetTouches[0].pageX : e.pageX;
                  s.touches.startY = s.touches.currentY = e.type === 'touchmove' ? e.targetTouches[0].pageY : e.pageY;
                  touchStartTime = Date.now();
              }
              return;
          }
          if (isTouchEvent && s.params.touchReleaseOnEdges && !s.params.loop) {
              if (!s.isHorizontal()) {
                  // Vertical
                  if (
                      (s.touches.currentY < s.touches.startY && s.translate <= s.maxTranslate()) ||
                      (s.touches.currentY > s.touches.startY && s.translate >= s.minTranslate())
                      ) {
                      return;
                  }
              }
              else {
                  if (
                      (s.touches.currentX < s.touches.startX && s.translate <= s.maxTranslate()) ||
                      (s.touches.currentX > s.touches.startX && s.translate >= s.minTranslate())
                      ) {
                      return;
                  }
              }
          }
          if (isTouchEvent && document.activeElement) {
              if (e.target === document.activeElement && $(e.target).is(formElements)) {
                  isMoved = true;
                  s.allowClick = false;
                  return;
              }
          }
          if (allowTouchCallbacks) {
              s.emit('onTouchMove', s, e);
          }
          if (e.targetTouches && e.targetTouches.length > 1) return;

          s.touches.currentX = e.type === 'touchmove' ? e.targetTouches[0].pageX : e.pageX;
          s.touches.currentY = e.type === 'touchmove' ? e.targetTouches[0].pageY : e.pageY;

          if (typeof isScrolling === 'undefined') {
              var touchAngle;
              if (s.isHorizontal() && s.touches.currentY === s.touches.startY || !s.isHorizontal() && s.touches.currentX === s.touches.startX) {
                  isScrolling = false;
              }
              else {
                  touchAngle = Math.atan2(Math.abs(s.touches.currentY - s.touches.startY), Math.abs(s.touches.currentX - s.touches.startX)) * 180 / Math.PI;
                  isScrolling = s.isHorizontal() ? touchAngle > s.params.touchAngle : (90 - touchAngle > s.params.touchAngle);
              }
          }
          if (isScrolling) {
              s.emit('onTouchMoveOpposite', s, e);
          }
          if (typeof startMoving === 'undefined') {
              if (s.touches.currentX !== s.touches.startX || s.touches.currentY !== s.touches.startY) {
                  startMoving = true;
              }
          }
          if (!isTouched) return;
          if (isScrolling)  {
              isTouched = false;
              return;
          }
          if (!startMoving) {
              return;
          }
          s.allowClick = false;
          s.emit('onSliderMove', s, e);
          e.preventDefault();
          if (s.params.touchMoveStopPropagation && !s.params.nested) {
              e.stopPropagation();
          }

          if (!isMoved) {
              if (params.loop) {
                  s.fixLoop();
              }
              startTranslate = s.getWrapperTranslate();
              s.setWrapperTransition(0);
              if (s.animating) {
                  s.wrapper.trigger('webkitTransitionEnd transitionend oTransitionEnd MSTransitionEnd msTransitionEnd');
              }
              if (s.params.autoplay && s.autoplaying) {
                  if (s.params.autoplayDisableOnInteraction) {
                      s.stopAutoplay();
                  }
                  else {
                      s.pauseAutoplay();
                  }
              }
              allowMomentumBounce = false;
              //Grab Cursor
              if (s.params.grabCursor && (s.params.allowSwipeToNext === true || s.params.allowSwipeToPrev === true)) {
                  s.setGrabCursor(true);
              }
          }
          isMoved = true;

          var diff = s.touches.diff = s.isHorizontal() ? s.touches.currentX - s.touches.startX : s.touches.currentY - s.touches.startY;

          diff = diff * s.params.touchRatio;
          if (s.rtl) diff = -diff;

          s.swipeDirection = diff > 0 ? 'prev' : 'next';
          currentTranslate = diff + startTranslate;

          var disableParentSwiper = true;
          if ((diff > 0 && currentTranslate > s.minTranslate())) {
              disableParentSwiper = false;
              if (s.params.resistance) currentTranslate = s.minTranslate() - 1 + Math.pow(-s.minTranslate() + startTranslate + diff, s.params.resistanceRatio);
          }
          else if (diff < 0 && currentTranslate < s.maxTranslate()) {
              disableParentSwiper = false;
              if (s.params.resistance) currentTranslate = s.maxTranslate() + 1 - Math.pow(s.maxTranslate() - startTranslate - diff, s.params.resistanceRatio);
          }

          if (disableParentSwiper) {
              e.preventedByNestedSwiper = true;
          }

          // Directions locks
          if (!s.params.allowSwipeToNext && s.swipeDirection === 'next' && currentTranslate < startTranslate) {
              currentTranslate = startTranslate;
          }
          if (!s.params.allowSwipeToPrev && s.swipeDirection === 'prev' && currentTranslate > startTranslate) {
              currentTranslate = startTranslate;
          }


          // Threshold
          if (s.params.threshold > 0) {
              if (Math.abs(diff) > s.params.threshold || allowThresholdMove) {
                  if (!allowThresholdMove) {
                      allowThresholdMove = true;
                      s.touches.startX = s.touches.currentX;
                      s.touches.startY = s.touches.currentY;
                      currentTranslate = startTranslate;
                      s.touches.diff = s.isHorizontal() ? s.touches.currentX - s.touches.startX : s.touches.currentY - s.touches.startY;
                      return;
                  }
              }
              else {
                  currentTranslate = startTranslate;
                  return;
              }
          }

          if (!s.params.followFinger) return;

          // Update active index in free mode
          if (s.params.freeMode || s.params.watchSlidesProgress) {
              s.updateActiveIndex();
          }
          if (s.params.freeMode) {
              //Velocity
              if (velocities.length === 0) {
                  velocities.push({
                      position: s.touches[s.isHorizontal() ? 'startX' : 'startY'],
                      time: touchStartTime
                  });
              }
              velocities.push({
                  position: s.touches[s.isHorizontal() ? 'currentX' : 'currentY'],
                  time: (new window.Date()).getTime()
              });
          }
          // Update progress
          s.updateProgress(currentTranslate);
          // Update translate
          s.setWrapperTranslate(currentTranslate);
      };
      s.onTouchEnd = function (e) {
          if (e.originalEvent) e = e.originalEvent;
          if (allowTouchCallbacks) {
              s.emit('onTouchEnd', s, e);
          }
          allowTouchCallbacks = false;
          if (!isTouched) return;
          //Return Grab Cursor
          if (s.params.grabCursor && isMoved && isTouched  && (s.params.allowSwipeToNext === true || s.params.allowSwipeToPrev === true)) {
              s.setGrabCursor(false);
          }

          // Time diff
          var touchEndTime = Date.now();
          var timeDiff = touchEndTime - touchStartTime;

          // Tap, doubleTap, Click
          if (s.allowClick) {
              s.updateClickedSlide(e);
              s.emit('onTap', s, e);
              if (timeDiff < 300 && (touchEndTime - lastClickTime) > 300) {
                  if (clickTimeout) clearTimeout(clickTimeout);
                  clickTimeout = setTimeout(function () {
                      if (!s) return;
                      if (s.params.paginationHide && s.paginationContainer.length > 0 && !$(e.target).hasClass(s.params.bulletClass)) {
                          s.paginationContainer.toggleClass(s.params.paginationHiddenClass);
                      }
                      s.emit('onClick', s, e);
                  }, 300);

              }
              if (timeDiff < 300 && (touchEndTime - lastClickTime) < 300) {
                  if (clickTimeout) clearTimeout(clickTimeout);
                  s.emit('onDoubleTap', s, e);
              }
          }

          lastClickTime = Date.now();
          setTimeout(function () {
              if (s) s.allowClick = true;
          }, 0);

          if (!isTouched || !isMoved || !s.swipeDirection || s.touches.diff === 0 || currentTranslate === startTranslate) {
              isTouched = isMoved = false;
              return;
          }
          isTouched = isMoved = false;

          var currentPos;
          if (s.params.followFinger) {
              currentPos = s.rtl ? s.translate : -s.translate;
          }
          else {
              currentPos = -currentTranslate;
          }
          if (s.params.freeMode) {
              if (currentPos < -s.minTranslate()) {
                  s.slideTo(s.activeIndex);
                  return;
              }
              else if (currentPos > -s.maxTranslate()) {
                  if (s.slides.length < s.snapGrid.length) {
                      s.slideTo(s.snapGrid.length - 1);
                  }
                  else {
                      s.slideTo(s.slides.length - 1);
                  }
                  return;
              }

              if (s.params.freeModeMomentum) {
                  if (velocities.length > 1) {
                      var lastMoveEvent = velocities.pop(), velocityEvent = velocities.pop();

                      var distance = lastMoveEvent.position - velocityEvent.position;
                      var time = lastMoveEvent.time - velocityEvent.time;
                      s.velocity = distance / time;
                      s.velocity = s.velocity / 2;
                      if (Math.abs(s.velocity) < s.params.freeModeMinimumVelocity) {
                          s.velocity = 0;
                      }
                      // this implies that the user stopped moving a finger then released.
                      // There would be no events with distance zero, so the last event is stale.
                      if (time > 150 || (new window.Date().getTime() - lastMoveEvent.time) > 300) {
                          s.velocity = 0;
                      }
                  } else {
                      s.velocity = 0;
                  }
                  s.velocity = s.velocity * s.params.freeModeMomentumVelocityRatio;

                  if ( s.params.freeModeMomentumMinimumVelocity && Math.abs(s.velocity) < s.params.freeModeMomentumMinimumVelocity ) {
                    s.velocity = s.velocity / Math.abs(s.velocity) * s.params.freeModeMomentumMinimumVelocity;
                  } else if ( s.params.freeModeMomentumMaximumVelocity && Math.abs(s.velocity) > s.params.freeModeMomentumMaximumVelocity ) {
                    s.velocity = s.velocity / Math.abs(s.velocity) * s.params.freeModeMomentumMaximumVelocity;
                  }

                  velocities.length = 0;
                  var momentumDuration = 1000 * s.params.freeModeMomentumRatio;
                  var momentumDistance = s.velocity * momentumDuration;

                  var newPosition = s.translate + momentumDistance;
                  if (s.rtl) newPosition = - newPosition;
                  var doBounce = false;
                  var afterBouncePosition;
                  var bounceAmount = Math.abs(s.velocity) * 20 * s.params.freeModeMomentumBounceRatio;
                  if (newPosition < s.maxTranslate()) {
                      if (s.params.freeModeMomentumBounce) {
                          if (newPosition + s.maxTranslate() < -bounceAmount) {
                              newPosition = s.maxTranslate() - bounceAmount;
                          }
                          afterBouncePosition = s.maxTranslate();
                          doBounce = true;
                          allowMomentumBounce = true;
                      }
                      else {
                          newPosition = s.maxTranslate();
                      }
                  }
                  else if (newPosition > s.minTranslate()) {
                      if (s.params.freeModeMomentumBounce) {
                          if (newPosition - s.minTranslate() > bounceAmount) {
                              newPosition = s.minTranslate() + bounceAmount;
                          }
                          afterBouncePosition = s.minTranslate();
                          doBounce = true;
                          allowMomentumBounce = true;
                      }
                      else {
                          newPosition = s.minTranslate();
                      }
                  }
                  else if (s.params.freeModeSticky) {
                      var j = 0,
                          nextSlide;
                      for (j = 0; j < s.snapGrid.length; j += 1) {
                          if (s.snapGrid[j] > -newPosition) {
                              nextSlide = j;
                              break;
                          }

                      }
                      if (Math.abs(s.snapGrid[nextSlide] - newPosition) < Math.abs(s.snapGrid[nextSlide - 1] - newPosition) || s.swipeDirection === 'next') {
                          newPosition = s.snapGrid[nextSlide];
                      } else {
                          newPosition = s.snapGrid[nextSlide - 1];
                      }
                      if (!s.rtl) newPosition = - newPosition;
                  }
                  //Fix duration
                  if (s.velocity !== 0) {
                      if (s.rtl) {
                          momentumDuration = Math.abs((-newPosition - s.translate) / s.velocity);
                      }
                      else {
                          momentumDuration = Math.abs((newPosition - s.translate) / s.velocity);
                      }
                  }
                  else if (s.params.freeModeSticky) {
                      s.slideReset();
                      return;
                  }

                  if (s.params.freeModeMomentumBounce && doBounce) {
                      s.updateProgress(afterBouncePosition);
                      s.setWrapperTransition(momentumDuration);
                      s.setWrapperTranslate(newPosition);
                      s.onTransitionStart();
                      s.animating = true;
                      s.wrapper.transitionEnd(function () {
                          if (!s || !allowMomentumBounce) return;
                          s.emit('onMomentumBounce', s);

                          s.setWrapperTransition(s.params.speed);
                          s.setWrapperTranslate(afterBouncePosition);
                          s.wrapper.transitionEnd(function () {
                              if (!s) return;
                              s.onTransitionEnd();
                          });
                      });
                  } else if (s.velocity) {
                      s.updateProgress(newPosition);
                      s.setWrapperTransition(momentumDuration);
                      s.setWrapperTranslate(newPosition);
                      s.onTransitionStart();
                      if (!s.animating) {
                          s.animating = true;
                          s.wrapper.transitionEnd(function () {
                              if (!s) return;
                              s.onTransitionEnd();
                          });
                      }

                  } else {
                      s.updateProgress(newPosition);
                  }

                  s.updateActiveIndex();
              }
              if (!s.params.freeModeMomentum || timeDiff >= s.params.longSwipesMs) {
                  s.updateProgress();
                  s.updateActiveIndex();
              }
              return;
          }

          // Find current slide
          var i, stopIndex = 0, groupSize = s.slidesSizesGrid[0];
          for (i = 0; i < s.slidesGrid.length; i += s.params.slidesPerGroup) {
              if (typeof s.slidesGrid[i + s.params.slidesPerGroup] !== 'undefined') {
                  if (currentPos >= s.slidesGrid[i] && currentPos < s.slidesGrid[i + s.params.slidesPerGroup]) {
                      stopIndex = i;
                      groupSize = s.slidesGrid[i + s.params.slidesPerGroup] - s.slidesGrid[i];
                  }
              }
              else {
                  if (currentPos >= s.slidesGrid[i]) {
                      stopIndex = i;
                      groupSize = s.slidesGrid[s.slidesGrid.length - 1] - s.slidesGrid[s.slidesGrid.length - 2];
                  }
              }
          }

          // Find current slide size
          var ratio = (currentPos - s.slidesGrid[stopIndex]) / groupSize;

          if (timeDiff > s.params.longSwipesMs) {
              // Long touches
              if (!s.params.longSwipes) {
                  s.slideTo(s.activeIndex);
                  return;
              }
              if (s.swipeDirection === 'next') {
                  if (ratio >= s.params.longSwipesRatio) s.slideTo(stopIndex + s.params.slidesPerGroup);
                  else s.slideTo(stopIndex);

              }
              if (s.swipeDirection === 'prev') {
                  if (ratio > (1 - s.params.longSwipesRatio)) s.slideTo(stopIndex + s.params.slidesPerGroup);
                  else s.slideTo(stopIndex);
              }
          }
          else {
              // Short swipes
              if (!s.params.shortSwipes) {
                  s.slideTo(s.activeIndex);
                  return;
              }
              if (s.swipeDirection === 'next') {
                  s.slideTo(stopIndex + s.params.slidesPerGroup);

              }
              if (s.swipeDirection === 'prev') {
                  s.slideTo(stopIndex);
              }
          }
      };
      /*=========================
        Transitions
        ===========================*/
      s._slideTo = function (slideIndex, speed) {
          return s.slideTo(slideIndex, speed, true, true);
      };
      s.slideTo = function (slideIndex, speed, runCallbacks, internal) {
          if (typeof runCallbacks === 'undefined') runCallbacks = true;
          if (typeof slideIndex === 'undefined') slideIndex = 0;
          if (slideIndex < 0) slideIndex = 0;
          s.snapIndex = Math.floor(slideIndex / s.params.slidesPerGroup);
          if (s.snapIndex >= s.snapGrid.length) s.snapIndex = s.snapGrid.length - 1;

          var translate = - s.snapGrid[s.snapIndex];
          // Stop autoplay
          if (s.params.autoplay && s.autoplaying) {
              if (internal || !s.params.autoplayDisableOnInteraction) {
                  s.pauseAutoplay(speed);
              }
              else {
                  s.stopAutoplay();
              }
          }
          // Update progress
          s.updateProgress(translate);

          // Normalize slideIndex
          if(s.params.normalizeSlideIndex){
              for (var i = 0; i < s.slidesGrid.length; i++) {
                  if (- Math.floor(translate * 100) >= Math.floor(s.slidesGrid[i] * 100)) {
                      slideIndex = i;
                  }
              }
          }

          // Directions locks
          if (!s.params.allowSwipeToNext && translate < s.translate && translate < s.minTranslate()) {
              return false;
          }
          if (!s.params.allowSwipeToPrev && translate > s.translate && translate > s.maxTranslate()) {
              if ((s.activeIndex || 0) !== slideIndex ) return false;
          }

          // Update Index
          if (typeof speed === 'undefined') speed = s.params.speed;
          s.previousIndex = s.activeIndex || 0;
          s.activeIndex = slideIndex;
          s.updateRealIndex();
          if ((s.rtl && -translate === s.translate) || (!s.rtl && translate === s.translate)) {
              // Update Height
              if (s.params.autoHeight) {
                  s.updateAutoHeight();
              }
              s.updateClasses();
              if (s.params.effect !== 'slide') {
                  s.setWrapperTranslate(translate);
              }
              return false;
          }
          s.updateClasses();
          s.onTransitionStart(runCallbacks);

          if (speed === 0 || s.browser.lteIE9) {
              s.setWrapperTranslate(translate);
              s.setWrapperTransition(0);
              s.onTransitionEnd(runCallbacks);
          }
          else {
              s.setWrapperTranslate(translate);
              s.setWrapperTransition(speed);
              if (!s.animating) {
                  s.animating = true;
                  s.wrapper.transitionEnd(function () {
                      if (!s) return;
                      s.onTransitionEnd(runCallbacks);
                  });
              }

          }

          return true;
      };

      s.onTransitionStart = function (runCallbacks) {
          if (typeof runCallbacks === 'undefined') runCallbacks = true;
          if (s.params.autoHeight) {
              s.updateAutoHeight();
          }
          if (s.lazy) s.lazy.onTransitionStart();
          if (runCallbacks) {
              s.emit('onTransitionStart', s);
              if (s.activeIndex !== s.previousIndex) {
                  s.emit('onSlideChangeStart', s);
                  if (s.activeIndex > s.previousIndex) {
                      s.emit('onSlideNextStart', s);
                  }
                  else {
                      s.emit('onSlidePrevStart', s);
                  }
              }

          }
      };
      s.onTransitionEnd = function (runCallbacks) {
          s.animating = false;
          s.setWrapperTransition(0);
          if (typeof runCallbacks === 'undefined') runCallbacks = true;
          if (s.lazy) s.lazy.onTransitionEnd();
          if (runCallbacks) {
              s.emit('onTransitionEnd', s);
              if (s.activeIndex !== s.previousIndex) {
                  s.emit('onSlideChangeEnd', s);
                  if (s.activeIndex > s.previousIndex) {
                      s.emit('onSlideNextEnd', s);
                  }
                  else {
                      s.emit('onSlidePrevEnd', s);
                  }
              }
          }
          if (s.params.history && s.history) {
              s.history.setHistory(s.params.history, s.activeIndex);
          }
          if (s.params.hashnav && s.hashnav) {
              s.hashnav.setHash();
          }

      };
      s.slideNext = function (runCallbacks, speed, internal) {
          if (s.params.loop) {
              if (s.animating) return false;
              s.fixLoop();
              var clientLeft = s.container[0].clientLeft;
              return s.slideTo(s.activeIndex + s.params.slidesPerGroup, speed, runCallbacks, internal);
          }
          else return s.slideTo(s.activeIndex + s.params.slidesPerGroup, speed, runCallbacks, internal);
      };
      s._slideNext = function (speed) {
          return s.slideNext(true, speed, true);
      };
      s.slidePrev = function (runCallbacks, speed, internal) {
          if (s.params.loop) {
              if (s.animating) return false;
              s.fixLoop();
              var clientLeft = s.container[0].clientLeft;
              return s.slideTo(s.activeIndex - 1, speed, runCallbacks, internal);
          }
          else return s.slideTo(s.activeIndex - 1, speed, runCallbacks, internal);
      };
      s._slidePrev = function (speed) {
          return s.slidePrev(true, speed, true);
      };
      s.slideReset = function (runCallbacks, speed, internal) {
          return s.slideTo(s.activeIndex, speed, runCallbacks);
      };

      s.disableTouchControl = function () {
          s.params.onlyExternal = true;
          return true;
      };
      s.enableTouchControl = function () {
          s.params.onlyExternal = false;
          return true;
      };

      /*=========================
        Translate/transition helpers
        ===========================*/
      s.setWrapperTransition = function (duration, byController) {
          s.wrapper.transition(duration);
          if (s.params.effect !== 'slide' && s.effects[s.params.effect]) {
              s.effects[s.params.effect].setTransition(duration);
          }
          if (s.params.parallax && s.parallax) {
              s.parallax.setTransition(duration);
          }
          if (s.params.scrollbar && s.scrollbar) {
              s.scrollbar.setTransition(duration);
          }
          if (s.params.control && s.controller) {
              s.controller.setTransition(duration, byController);
          }
          s.emit('onSetTransition', s, duration);
      };
      s.setWrapperTranslate = function (translate, updateActiveIndex, byController) {
          var x = 0, y = 0, z = 0;
          if (s.isHorizontal()) {
              x = s.rtl ? -translate : translate;
          }
          else {
              y = translate;
          }

          if (s.params.roundLengths) {
              x = round(x);
              y = round(y);
          }

          if (!s.params.virtualTranslate) {
              if (s.support.transforms3d) s.wrapper.transform('translate3d(' + x + 'px, ' + y + 'px, ' + z + 'px)');
              else s.wrapper.transform('translate(' + x + 'px, ' + y + 'px)');
          }

          s.translate = s.isHorizontal() ? x : y;

          // Check if we need to update progress
          var progress;
          var translatesDiff = s.maxTranslate() - s.minTranslate();
          if (translatesDiff === 0) {
              progress = 0;
          }
          else {
              progress = (translate - s.minTranslate()) / (translatesDiff);
          }
          if (progress !== s.progress) {
              s.updateProgress(translate);
          }

          if (updateActiveIndex) s.updateActiveIndex();
          if (s.params.effect !== 'slide' && s.effects[s.params.effect]) {
              s.effects[s.params.effect].setTranslate(s.translate);
          }
          if (s.params.parallax && s.parallax) {
              s.parallax.setTranslate(s.translate);
          }
          if (s.params.scrollbar && s.scrollbar) {
              s.scrollbar.setTranslate(s.translate);
          }
          if (s.params.control && s.controller) {
              s.controller.setTranslate(s.translate, byController);
          }
          s.emit('onSetTranslate', s, s.translate);
      };

      s.getTranslate = function (el, axis) {
          var matrix, curTransform, curStyle, transformMatrix;

          // automatic axis detection
          if (typeof axis === 'undefined') {
              axis = 'x';
          }

          if (s.params.virtualTranslate) {
              return s.rtl ? -s.translate : s.translate;
          }

          curStyle = window.getComputedStyle(el, null);
          if (window.WebKitCSSMatrix) {
              curTransform = curStyle.transform || curStyle.webkitTransform;
              if (curTransform.split(',').length > 6) {
                  curTransform = curTransform.split(', ').map(function(a){
                      return a.replace(',','.');
                  }).join(', ');
              }
              // Some old versions of Webkit choke when 'none' is passed; pass
              // empty string instead in this case
              transformMatrix = new window.WebKitCSSMatrix(curTransform === 'none' ? '' : curTransform);
          }
          else {
              transformMatrix = curStyle.MozTransform || curStyle.OTransform || curStyle.MsTransform || curStyle.msTransform  || curStyle.transform || curStyle.getPropertyValue('transform').replace('translate(', 'matrix(1, 0, 0, 1,');
              matrix = transformMatrix.toString().split(',');
          }

          if (axis === 'x') {
              //Latest Chrome and webkits Fix
              if (window.WebKitCSSMatrix)
                  curTransform = transformMatrix.m41;
              //Crazy IE10 Matrix
              else if (matrix.length === 16)
                  curTransform = parseFloat(matrix[12]);
              //Normal Browsers
              else
                  curTransform = parseFloat(matrix[4]);
          }
          if (axis === 'y') {
              //Latest Chrome and webkits Fix
              if (window.WebKitCSSMatrix)
                  curTransform = transformMatrix.m42;
              //Crazy IE10 Matrix
              else if (matrix.length === 16)
                  curTransform = parseFloat(matrix[13]);
              //Normal Browsers
              else
                  curTransform = parseFloat(matrix[5]);
          }
          if (s.rtl && curTransform) curTransform = -curTransform;
          return curTransform || 0;
      };
      s.getWrapperTranslate = function (axis) {
          if (typeof axis === 'undefined') {
              axis = s.isHorizontal() ? 'x' : 'y';
          }
          return s.getTranslate(s.wrapper[0], axis);
      };

    /*=========================
    Observer
    ===========================*/
    s.observers = [];
    function initObserver(target, options) {
        options = options || {};
        // create an observer instance
        var ObserverFunc = window.MutationObserver || window.WebkitMutationObserver;
        var observer = new ObserverFunc(function (mutations) {
            mutations.forEach(function (mutation) {
                s.onResize(true);
                s.emit('onObserverUpdate', s, mutation);
            });
        });

        observer.observe(target, {
            attributes: typeof options.attributes === 'undefined' ? true : options.attributes,
            childList: typeof options.childList === 'undefined' ? true : options.childList,
            characterData: typeof options.characterData === 'undefined' ? true : options.characterData
        });

        s.observers.push(observer);
    }
    s.initObservers = function () {
        if (s.params.observeParents) {
            var containerParents = s.container.parents();
            for (var i = 0; i < containerParents.length; i++) {
                initObserver(containerParents[i]);
            }
        }

        // Observe container
        initObserver(s.container[0], {childList: false});

        // Observe wrapper
        initObserver(s.wrapper[0], {attributes: false});
    };
    s.disconnectObservers = function () {
        for (var i = 0; i < s.observers.length; i++) {
            s.observers[i].disconnect();
        }
        s.observers = [];
    };
    /*=========================
    Loop
    ===========================*/
    // Create looped slides
    s.createLoop = function () {
        // Remove duplicated slides
        s.wrapper.children('.' + s.params.slideClass + '.' + s.params.slideDuplicateClass).remove();

        var slides = s.wrapper.children('.' + s.params.slideClass);

        if(s.params.slidesPerView === 'auto' && !s.params.loopedSlides) s.params.loopedSlides = slides.length;

        s.loopedSlides = parseInt(s.params.loopedSlides || s.params.slidesPerView, 10);
        s.loopedSlides = s.loopedSlides + s.params.loopAdditionalSlides;
        if (s.loopedSlides > slides.length) {
            s.loopedSlides = slides.length;
        }

        var prependSlides = [], appendSlides = [], i;
        slides.each(function (index, el) {
            var slide = $(this);
            if (index < s.loopedSlides) appendSlides.push(el);
            if (index < slides.length && index >= slides.length - s.loopedSlides) prependSlides.push(el);
            slide.attr('data-swiper-slide-index', index);
        });
        for (i = 0; i < appendSlides.length; i++) {
            s.wrapper.append($(appendSlides[i].cloneNode(true)).addClass(s.params.slideDuplicateClass));
        }
        for (i = prependSlides.length - 1; i >= 0; i--) {
            s.wrapper.prepend($(prependSlides[i].cloneNode(true)).addClass(s.params.slideDuplicateClass));
        }
    };
    s.destroyLoop = function () {
        s.wrapper.children('.' + s.params.slideClass + '.' + s.params.slideDuplicateClass).remove();
        s.slides.removeAttr('data-swiper-slide-index');
    };
    s.reLoop = function (updatePosition) {
        var oldIndex = s.activeIndex - s.loopedSlides;
        s.destroyLoop();
        s.createLoop();
        s.updateSlidesSize();
        if (updatePosition) {
            s.slideTo(oldIndex + s.loopedSlides, 0, false);
        }

    };
    s.fixLoop = function () {
        var newIndex;
        //Fix For Negative Oversliding
        if (s.activeIndex < s.loopedSlides) {
            newIndex = s.slides.length - s.loopedSlides * 3 + s.activeIndex;
            newIndex = newIndex + s.loopedSlides;
            s.slideTo(newIndex, 0, false, true);
        }
        //Fix For Positive Oversliding
        else if ((s.params.slidesPerView === 'auto' && s.activeIndex >= s.loopedSlides * 2) || (s.activeIndex > s.slides.length - s.params.slidesPerView * 2)) {
            newIndex = -s.slides.length + s.activeIndex + s.loopedSlides;
            newIndex = newIndex + s.loopedSlides;
            s.slideTo(newIndex, 0, false, true);
        }
    };
    /*=========================
    Append/Prepend/Remove Slides
    ===========================*/
    s.appendSlide = function (slides) {
        if (s.params.loop) {
            s.destroyLoop();
        }
        if (typeof slides === 'object' && slides.length) {
            for (var i = 0; i < slides.length; i++) {
                if (slides[i]) s.wrapper.append(slides[i]);
            }
        }
        else {
            s.wrapper.append(slides);
        }
        if (s.params.loop) {
            s.createLoop();
        }
        if (!(s.params.observer && s.support.observer)) {
            s.update(true);
        }
    };
    s.prependSlide = function (slides) {
        if (s.params.loop) {
            s.destroyLoop();
        }
        var newActiveIndex = s.activeIndex + 1;
        if (typeof slides === 'object' && slides.length) {
            for (var i = 0; i < slides.length; i++) {
                if (slides[i]) s.wrapper.prepend(slides[i]);
            }
            newActiveIndex = s.activeIndex + slides.length;
        }
        else {
            s.wrapper.prepend(slides);
        }
        if (s.params.loop) {
            s.createLoop();
        }
        if (!(s.params.observer && s.support.observer)) {
            s.update(true);
        }
        s.slideTo(newActiveIndex, 0, false);
    };
    s.removeSlide = function (slidesIndexes) {
        if (s.params.loop) {
            s.destroyLoop();
            s.slides = s.wrapper.children('.' + s.params.slideClass);
        }
        var newActiveIndex = s.activeIndex,
            indexToRemove;
        if (typeof slidesIndexes === 'object' && slidesIndexes.length) {
            for (var i = 0; i < slidesIndexes.length; i++) {
                indexToRemove = slidesIndexes[i];
                if (s.slides[indexToRemove]) s.slides.eq(indexToRemove).remove();
                if (indexToRemove < newActiveIndex) newActiveIndex--;
            }
            newActiveIndex = Math.max(newActiveIndex, 0);
        }
        else {
            indexToRemove = slidesIndexes;
            if (s.slides[indexToRemove]) s.slides.eq(indexToRemove).remove();
            if (indexToRemove < newActiveIndex) newActiveIndex--;
            newActiveIndex = Math.max(newActiveIndex, 0);
        }

        if (s.params.loop) {
            s.createLoop();
        }

        if (!(s.params.observer && s.support.observer)) {
            s.update(true);
        }
        if (s.params.loop) {
            s.slideTo(newActiveIndex + s.loopedSlides, 0, false);
        }
        else {
            s.slideTo(newActiveIndex, 0, false);
        }

    };
    s.removeAllSlides = function () {
        var slidesIndexes = [];
        for (var i = 0; i < s.slides.length; i++) {
            slidesIndexes.push(i);
        }
        s.removeSlide(slidesIndexes);
    };


      /*=========================
        Effects
        ===========================*/
    s.effects = {
        fade: {
            setTranslate: function () {
                for (var i = 0; i < s.slides.length; i++) {
                    var slide = s.slides.eq(i);
                    var offset = slide[0].swiperSlideOffset;
                    var tx = -offset;
                    if (!s.params.virtualTranslate) tx = tx - s.translate;
                    var ty = 0;
                    if (!s.isHorizontal()) {
                        ty = tx;
                        tx = 0;
                    }
                    var slideOpacity = s.params.fade.crossFade ?
                            Math.max(1 - Math.abs(slide[0].progress), 0) :
                            1 + Math.min(Math.max(slide[0].progress, -1), 0);
                    slide.css({opacity: slideOpacity});
                    slide.transform('translate3d(' + tx + 'px, ' + ty + 'px, 0px)');
                }
            },
            setTransition: function (duration) {
                s.slides.transition(duration);
                if (s.params.virtualTranslate && duration !== 0) {
                    var eventTriggered = false;
                    s.slides.transitionEnd(function () {
                        if (eventTriggered) return;
                        if (!s) return;
                        eventTriggered = true;
                        s.animating = false;
                        var triggerEvents = ['webkitTransitionEnd', 'transitionend', 'oTransitionEnd', 'MSTransitionEnd', 'msTransitionEnd'];
                        for (var i = 0; i < triggerEvents.length; i++) {
                            s.wrapper.trigger(triggerEvents[i]);
                        }
                    });
                }
            }
        },
        flip: {
            setTranslate: function () {
                for (var i = 0; i < s.slides.length; i++) {
                    var slide = s.slides.eq(i);
                    var progress = slide[0].progress;
                    if (s.params.flip.limitRotation) {
                        progress = Math.max(Math.min(slide[0].progress, 1), -1);
                    }
                    var offset = slide[0].swiperSlideOffset;
                    var rotate = -180 * progress,
                        rotateY = rotate,
                        rotateX = 0,
                        tx = -offset,
                        ty = 0;
                    if (!s.isHorizontal()) {
                        ty = tx;
                        tx = 0;
                        rotateX = -rotateY;
                        rotateY = 0;
                    }
                    else if (s.rtl) {
                        rotateY = -rotateY;
                    }

                    slide[0].style.zIndex = -Math.abs(Math.round(progress)) + s.slides.length;

                    if (s.params.flip.slideShadows) {
                        //Set shadows
                        var shadowBefore = s.isHorizontal() ? slide.find('.swiper-slide-shadow-left') : slide.find('.swiper-slide-shadow-top');
                        var shadowAfter = s.isHorizontal() ? slide.find('.swiper-slide-shadow-right') : slide.find('.swiper-slide-shadow-bottom');
                        if (shadowBefore.length === 0) {
                            shadowBefore = $('<div class="swiper-slide-shadow-' + (s.isHorizontal() ? 'left' : 'top') + '"></div>');
                            slide.append(shadowBefore);
                        }
                        if (shadowAfter.length === 0) {
                            shadowAfter = $('<div class="swiper-slide-shadow-' + (s.isHorizontal() ? 'right' : 'bottom') + '"></div>');
                            slide.append(shadowAfter);
                        }
                        if (shadowBefore.length) shadowBefore[0].style.opacity = Math.max(-progress, 0);
                        if (shadowAfter.length) shadowAfter[0].style.opacity = Math.max(progress, 0);
                    }

                    slide
                        .transform('translate3d(' + tx + 'px, ' + ty + 'px, 0px) rotateX(' + rotateX + 'deg) rotateY(' + rotateY + 'deg)');
                }
            },
            setTransition: function (duration) {
                s.slides.transition(duration).find('.swiper-slide-shadow-top, .swiper-slide-shadow-right, .swiper-slide-shadow-bottom, .swiper-slide-shadow-left').transition(duration);
                if (s.params.virtualTranslate && duration !== 0) {
                    var eventTriggered = false;
                    s.slides.eq(s.activeIndex).transitionEnd(function () {
                        if (eventTriggered) return;
                        if (!s) return;
                        if (!$(this).hasClass(s.params.slideActiveClass)) return;
                        eventTriggered = true;
                        s.animating = false;
                        var triggerEvents = ['webkitTransitionEnd', 'transitionend', 'oTransitionEnd', 'MSTransitionEnd', 'msTransitionEnd'];
                        for (var i = 0; i < triggerEvents.length; i++) {
                            s.wrapper.trigger(triggerEvents[i]);
                        }
                    });
                }
            }
        },
        cube: {
            setTranslate: function () {
                var wrapperRotate = 0, cubeShadow;
                if (s.params.cube.shadow) {
                    if (s.isHorizontal()) {
                        cubeShadow = s.wrapper.find('.swiper-cube-shadow');
                        if (cubeShadow.length === 0) {
                            cubeShadow = $('<div class="swiper-cube-shadow"></div>');
                            s.wrapper.append(cubeShadow);
                        }
                        cubeShadow.css({height: s.width + 'px'});
                    }
                    else {
                        cubeShadow = s.container.find('.swiper-cube-shadow');
                        if (cubeShadow.length === 0) {
                            cubeShadow = $('<div class="swiper-cube-shadow"></div>');
                            s.container.append(cubeShadow);
                        }
                    }
                }
                for (var i = 0; i < s.slides.length; i++) {
                    var slide = s.slides.eq(i);
                    var slideAngle = i * 90;
                    var round = Math.floor(slideAngle / 360);
                    if (s.rtl) {
                        slideAngle = -slideAngle;
                        round = Math.floor(-slideAngle / 360);
                    }
                    var progress = Math.max(Math.min(slide[0].progress, 1), -1);
                    var tx = 0, ty = 0, tz = 0;
                    if (i % 4 === 0) {
                        tx = - round * 4 * s.size;
                        tz = 0;
                    }
                    else if ((i - 1) % 4 === 0) {
                        tx = 0;
                        tz = - round * 4 * s.size;
                    }
                    else if ((i - 2) % 4 === 0) {
                        tx = s.size + round * 4 * s.size;
                        tz = s.size;
                    }
                    else if ((i - 3) % 4 === 0) {
                        tx = - s.size;
                        tz = 3 * s.size + s.size * 4 * round;
                    }
                    if (s.rtl) {
                        tx = -tx;
                    }

                    if (!s.isHorizontal()) {
                        ty = tx;
                        tx = 0;
                    }

                    var transform = 'rotateX(' + (s.isHorizontal() ? 0 : -slideAngle) + 'deg) rotateY(' + (s.isHorizontal() ? slideAngle : 0) + 'deg) translate3d(' + tx + 'px, ' + ty + 'px, ' + tz + 'px)';
                    if (progress <= 1 && progress > -1) {
                        wrapperRotate = i * 90 + progress * 90;
                        if (s.rtl) wrapperRotate = -i * 90 - progress * 90;
                    }
                    slide.transform(transform);
                    if (s.params.cube.slideShadows) {
                        //Set shadows
                        var shadowBefore = s.isHorizontal() ? slide.find('.swiper-slide-shadow-left') : slide.find('.swiper-slide-shadow-top');
                        var shadowAfter = s.isHorizontal() ? slide.find('.swiper-slide-shadow-right') : slide.find('.swiper-slide-shadow-bottom');
                        if (shadowBefore.length === 0) {
                            shadowBefore = $('<div class="swiper-slide-shadow-' + (s.isHorizontal() ? 'left' : 'top') + '"></div>');
                            slide.append(shadowBefore);
                        }
                        if (shadowAfter.length === 0) {
                            shadowAfter = $('<div class="swiper-slide-shadow-' + (s.isHorizontal() ? 'right' : 'bottom') + '"></div>');
                            slide.append(shadowAfter);
                        }
                        if (shadowBefore.length) shadowBefore[0].style.opacity = Math.max(-progress, 0);
                        if (shadowAfter.length) shadowAfter[0].style.opacity = Math.max(progress, 0);
                    }
                }
                s.wrapper.css({
                    '-webkit-transform-origin': '50% 50% -' + (s.size / 2) + 'px',
                    '-moz-transform-origin': '50% 50% -' + (s.size / 2) + 'px',
                    '-ms-transform-origin': '50% 50% -' + (s.size / 2) + 'px',
                    'transform-origin': '50% 50% -' + (s.size / 2) + 'px'
                });

                if (s.params.cube.shadow) {
                    if (s.isHorizontal()) {
                        cubeShadow.transform('translate3d(0px, ' + (s.width / 2 + s.params.cube.shadowOffset) + 'px, ' + (-s.width / 2) + 'px) rotateX(90deg) rotateZ(0deg) scale(' + (s.params.cube.shadowScale) + ')');
                    }
                    else {
                        var shadowAngle = Math.abs(wrapperRotate) - Math.floor(Math.abs(wrapperRotate) / 90) * 90;
                        var multiplier = 1.5 - (Math.sin(shadowAngle * 2 * Math.PI / 360) / 2 + Math.cos(shadowAngle * 2 * Math.PI / 360) / 2);
                        var scale1 = s.params.cube.shadowScale,
                            scale2 = s.params.cube.shadowScale / multiplier,
                            offset = s.params.cube.shadowOffset;
                        cubeShadow.transform('scale3d(' + scale1 + ', 1, ' + scale2 + ') translate3d(0px, ' + (s.height / 2 + offset) + 'px, ' + (-s.height / 2 / scale2) + 'px) rotateX(-90deg)');
                    }
                }
                var zFactor = (s.isSafari || s.isUiWebView) ? (-s.size / 2) : 0;
                s.wrapper.transform('translate3d(0px,0,' + zFactor + 'px) rotateX(' + (s.isHorizontal() ? 0 : wrapperRotate) + 'deg) rotateY(' + (s.isHorizontal() ? -wrapperRotate : 0) + 'deg)');
            },
            setTransition: function (duration) {
                s.slides.transition(duration).find('.swiper-slide-shadow-top, .swiper-slide-shadow-right, .swiper-slide-shadow-bottom, .swiper-slide-shadow-left').transition(duration);
                if (s.params.cube.shadow && !s.isHorizontal()) {
                    s.container.find('.swiper-cube-shadow').transition(duration);
                }
            }
        },
        coverflow: {
            setTranslate: function () {
                var transform = s.translate;
                var center = s.isHorizontal() ? -transform + s.width / 2 : -transform + s.height / 2;
                var rotate = s.isHorizontal() ? s.params.coverflow.rotate: -s.params.coverflow.rotate;
                var translate = s.params.coverflow.depth;
                //Each slide offset from center
                for (var i = 0, length = s.slides.length; i < length; i++) {
                    var slide = s.slides.eq(i);
                    var slideSize = s.slidesSizesGrid[i];
                    var slideOffset = slide[0].swiperSlideOffset;
                    var offsetMultiplier = (center - slideOffset - slideSize / 2) / slideSize * s.params.coverflow.modifier;

                    var rotateY = s.isHorizontal() ? rotate * offsetMultiplier : 0;
                    var rotateX = s.isHorizontal() ? 0 : rotate * offsetMultiplier;
                    // var rotateZ = 0
                    var translateZ = -translate * Math.abs(offsetMultiplier);

                    var translateY = s.isHorizontal() ? 0 : s.params.coverflow.stretch * (offsetMultiplier);
                    var translateX = s.isHorizontal() ? s.params.coverflow.stretch * (offsetMultiplier) : 0;

                    //Fix for ultra small values
                    if (Math.abs(translateX) < 0.001) translateX = 0;
                    if (Math.abs(translateY) < 0.001) translateY = 0;
                    if (Math.abs(translateZ) < 0.001) translateZ = 0;
                    if (Math.abs(rotateY) < 0.001) rotateY = 0;
                    if (Math.abs(rotateX) < 0.001) rotateX = 0;

                    var slideTransform = 'translate3d(' + translateX + 'px,' + translateY + 'px,' + translateZ + 'px)  rotateX(' + rotateX + 'deg) rotateY(' + rotateY + 'deg)';

                    slide.transform(slideTransform);

                    var zIndex = -Math.abs(Math.round(offsetMultiplier)) + 1;

                    slide[0].style.zIndex = zIndex;
                    if (s.params.coverflow.slideShadows) {
                        //Set shadows
                        var shadowBefore = s.isHorizontal() ? slide.find('.swiper-slide-shadow-left') : slide.find('.swiper-slide-shadow-top');
                        var shadowAfter = s.isHorizontal() ? slide.find('.swiper-slide-shadow-right') : slide.find('.swiper-slide-shadow-bottom');
                        if (shadowBefore.length === 0) {
                            shadowBefore = $('<div class="swiper-slide-shadow-' + (s.isHorizontal() ? 'left' : 'top') + '"></div>');
                            slide.append(shadowBefore);
                        }
                        if (shadowAfter.length === 0) {
                            shadowAfter = $('<div class="swiper-slide-shadow-' + (s.isHorizontal() ? 'right' : 'bottom') + '"></div>');
                            slide.append(shadowAfter);
                        }
                        if (shadowBefore.length) shadowBefore[0].style.opacity = offsetMultiplier > 0 ? offsetMultiplier : 0;
                        if (shadowAfter.length) shadowAfter[0].style.opacity = (-offsetMultiplier) > 0 ? -offsetMultiplier : 0;
                    }
                }

                //Set correct perspective for IE10
                if (s.browser.ie) {
                    var ws = s.wrapper[0].style;
                    ws.perspectiveOrigin = center + 'px 50%';
                }
            },
            setTransition: function (duration) {
                s.slides.transition(duration).find('.swiper-slide-shadow-top, .swiper-slide-shadow-right, .swiper-slide-shadow-bottom, .swiper-slide-shadow-left').transition(duration);
            }
        },
        itunes: {

            setTranslate: function () {

                var transform = s.translate;
                var center = s.isHorizontal() ? -transform + s.width / 2 : -transform + s.height / 2;
                var translate = s.params.itunes.depth;

                //Each slide offset from center
                for (var i = 0, length = s.slides.length; i < length; i++) {
                    var slide = s.slides.eq(i);
                    var slideSize = s.slidesSizesGrid[i];
                    var slideOffset = slide[0].swiperSlideOffset;
                    var offsetMultiplier = (center - slideOffset - slideSize / 2) / slideSize * s.params.itunes.modifier;

                    var translateZ = -translate * Math.abs(offsetMultiplier);

                    //Fix for ultra small values
                    if (Math.abs(translateZ) < 0.001) translateZ = 0;

                    // Fix hover in Safari
                    // linear fit {0,1},{-114.856, 328.55/360},{-229.712, 302.16/360},{-344.569, 279.69/360}
                    var scale = s.params.itunes.scaleMultiplier * translateZ + s.params.itunes.scaleOffset;
                    var slideTransform = 'scale(' + scale + ') translateZ(0)';

                    slide.transform(slideTransform);

                    var zIndex = -Math.abs(Math.round(offsetMultiplier*10)) + 1;
                    slide[0].style.zIndex = zIndex;
                }

                //Set correct perspective for IE10
                if (s.browser.ie) {
                    var ws = s.wrapper[0].style;
                    ws.perspectiveOrigin = center + 'px 50%';
                }
            },
            setTransition: function (duration) {
                s.slides.transition(duration).find('.swiper-slide-shadow-top, .swiper-slide-shadow-right, .swiper-slide-shadow-bottom, .swiper-slide-shadow-left').transition(duration);
            }
        }
    };


    /*=========================
    Images Lazy Loading
    ===========================*/
    s.lazy = {
        initialImageLoaded: false,
        loadImageInSlide: function (index, loadInDuplicate) {
            if (typeof index === 'undefined') return;
            if (typeof loadInDuplicate === 'undefined') loadInDuplicate = true;
            if (s.slides.length === 0) return;

            var slide = s.slides.eq(index);
            var img = slide.find('.' + s.params.lazyLoadingClass + ':not(.' + s.params.lazyStatusLoadedClass + '):not(.' + s.params.lazyStatusLoadingClass + ')');
            if (slide.hasClass(s.params.lazyLoadingClass) && !slide.hasClass(s.params.lazyStatusLoadedClass) && !slide.hasClass(s.params.lazyStatusLoadingClass)) {
                img = img.add(slide[0]);
            }
            if (img.length === 0) return;

            img.each(function () {
                var _img = $(this);
                _img.addClass(s.params.lazyStatusLoadingClass);
                var background = _img.attr('data-background');
                var src = _img.attr('data-src'),
                    srcset = _img.attr('data-srcset'),
                    sizes = _img.attr('data-sizes');
                s.loadImage(_img[0], (src || background), srcset, sizes, false, function () {
                    if (typeof s === 'undefined' || s === null || !s) return;
                    if (background) {
                        _img.css('background-image', 'url("' + background + '")');
                        _img.removeAttr('data-background');
                    }
                    else {
                        if (srcset) {
                            _img.attr('srcset', srcset);
                            _img.removeAttr('data-srcset');
                        }
                        if (sizes) {
                            _img.attr('sizes', sizes);
                            _img.removeAttr('data-sizes');
                        }
                        if (src) {
                            _img.attr('src', src);
                            _img.removeAttr('data-src');
                        }

                    }

                    _img.addClass(s.params.lazyStatusLoadedClass).removeClass(s.params.lazyStatusLoadingClass);
                    slide.find('.' + s.params.lazyPreloaderClass + ', .' + s.params.preloaderClass).remove();
                    if (s.params.loop && loadInDuplicate) {
                        var slideOriginalIndex = slide.attr('data-swiper-slide-index');
                        if (slide.hasClass(s.params.slideDuplicateClass)) {
                            var originalSlide = s.wrapper.children('[data-swiper-slide-index="' + slideOriginalIndex + '"]:not(.' + s.params.slideDuplicateClass + ')');
                            s.lazy.loadImageInSlide(originalSlide.index(), false);
                        }
                        else {
                            var duplicatedSlide = s.wrapper.children('.' + s.params.slideDuplicateClass + '[data-swiper-slide-index="' + slideOriginalIndex + '"]');
                            s.lazy.loadImageInSlide(duplicatedSlide.index(), false);
                        }
                    }
                    s.emit('onLazyImageReady', s, slide[0], _img[0]);
                });

                s.emit('onLazyImageLoad', s, slide[0], _img[0]);
            });

        },
        load: function () {
            var i;
            var slidesPerView = s.params.slidesPerView;
            if (slidesPerView === 'auto') {
                slidesPerView = 0;
            }
            if (!s.lazy.initialImageLoaded) s.lazy.initialImageLoaded = true;
            if (s.params.watchSlidesVisibility) {
                s.wrapper.children('.' + s.params.slideVisibleClass).each(function () {
                    s.lazy.loadImageInSlide($(this).index());
                });
            }
            else {
                if (slidesPerView > 1) {
                    for (i = s.activeIndex; i < s.activeIndex + slidesPerView ; i++) {
                        if (s.slides[i]) s.lazy.loadImageInSlide(i);
                    }
                }
                else {
                    s.lazy.loadImageInSlide(s.activeIndex);
                }
            }
            if (s.params.lazyLoadingInPrevNext) {
                if (slidesPerView > 1 || (s.params.lazyLoadingInPrevNextAmount && s.params.lazyLoadingInPrevNextAmount > 1)) {
                    var amount = s.params.lazyLoadingInPrevNextAmount;
                    var spv = slidesPerView;
                    var maxIndex = Math.min(s.activeIndex + spv + Math.max(amount, spv), s.slides.length);
                    var minIndex = Math.max(s.activeIndex - Math.max(spv, amount), 0);
                    // Next Slides
                    for (i = s.activeIndex + slidesPerView; i < maxIndex; i++) {
                        if (s.slides[i]) s.lazy.loadImageInSlide(i);
                    }
                    // Prev Slides
                    for (i = minIndex; i < s.activeIndex ; i++) {
                        if (s.slides[i]) s.lazy.loadImageInSlide(i);
                    }
                }
                else {
                    var nextSlide = s.wrapper.children('.' + s.params.slideNextClass);
                    if (nextSlide.length > 0) s.lazy.loadImageInSlide(nextSlide.index());

                    var prevSlide = s.wrapper.children('.' + s.params.slidePrevClass);
                    if (prevSlide.length > 0) s.lazy.loadImageInSlide(prevSlide.index());
                }
            }
        },
        onTransitionStart: function () {
            if (s.params.lazyLoading) {
                if (s.params.lazyLoadingOnTransitionStart || (!s.params.lazyLoadingOnTransitionStart && !s.lazy.initialImageLoaded)) {
                    s.lazy.load();
                }
            }
        },
        onTransitionEnd: function () {
            if (s.params.lazyLoading && !s.params.lazyLoadingOnTransitionStart) {
                s.lazy.load();
            }
        }
    };


    /*=========================
    Scrollbar
    ===========================*/
    s.scrollbar = {
        isTouched: false,
        setDragPosition: function (e) {
            var sb = s.scrollbar;
            var x = 0, y = 0;
            var translate;
            var pointerPosition = s.isHorizontal() ?
                ((e.type === 'touchstart' || e.type === 'touchmove') ? e.targetTouches[0].pageX : e.pageX || e.clientX) :
                ((e.type === 'touchstart' || e.type === 'touchmove') ? e.targetTouches[0].pageY : e.pageY || e.clientY) ;
            var position = (pointerPosition) - sb.track.offset()[s.isHorizontal() ? 'left' : 'top'] - sb.dragSize / 2;
            var positionMin = -s.minTranslate() * sb.moveDivider;
            var positionMax = -s.maxTranslate() * sb.moveDivider;
            if (position < positionMin) {
                position = positionMin;
            }
            else if (position > positionMax) {
                position = positionMax;
            }
            position = -position / sb.moveDivider;
            s.updateProgress(position);
            s.setWrapperTranslate(position, true);
        },
        dragStart: function (e) {
            var sb = s.scrollbar;
            sb.isTouched = true;
            e.preventDefault();
            e.stopPropagation();

            sb.setDragPosition(e);
            clearTimeout(sb.dragTimeout);

            sb.track.transition(0);
            if (s.params.scrollbarHide) {
                sb.track.css('opacity', 1);
            }
            s.wrapper.transition(100);
            sb.drag.transition(100);
            s.emit('onScrollbarDragStart', s);
        },
        dragMove: function (e) {
            var sb = s.scrollbar;
            if (!sb.isTouched) return;
            if (e.preventDefault) e.preventDefault();
            else e.returnValue = false;
            sb.setDragPosition(e);
            s.wrapper.transition(0);
            sb.track.transition(0);
            sb.drag.transition(0);
            s.emit('onScrollbarDragMove', s);
        },
        dragEnd: function (e) {
            var sb = s.scrollbar;
            if (!sb.isTouched) return;
            sb.isTouched = false;
            if (s.params.scrollbarHide) {
                clearTimeout(sb.dragTimeout);
                sb.dragTimeout = setTimeout(function () {
                    sb.track.css('opacity', 0);
                    sb.track.transition(400);
                }, 1000);

            }
            s.emit('onScrollbarDragEnd', s);
            if (s.params.scrollbarSnapOnRelease) {
                s.slideReset();
            }
        },
        draggableEvents: (function () {
            if ((s.params.simulateTouch === false && !s.support.touch)) return s.touchEventsDesktop;
            else return s.touchEvents;
        })(),
        enableDraggable: function () {
            var sb = s.scrollbar;
            var target = s.support.touch ? sb.track : document;
            $(sb.track).on(sb.draggableEvents.start, sb.dragStart);
            $(target).on(sb.draggableEvents.move, sb.dragMove);
            $(target).on(sb.draggableEvents.end, sb.dragEnd);
        },
        disableDraggable: function () {
            var sb = s.scrollbar;
            var target = s.support.touch ? sb.track : document;
            $(sb.track).off(sb.draggableEvents.start, sb.dragStart);
            $(target).off(sb.draggableEvents.move, sb.dragMove);
            $(target).off(sb.draggableEvents.end, sb.dragEnd);
        },
        set: function () {
            if (!s.params.scrollbar) return;
            var sb = s.scrollbar;
            sb.track = $(s.params.scrollbar);
            if (s.params.uniqueNavElements && typeof s.params.scrollbar === 'string' && sb.track.length > 1 && s.container.find(s.params.scrollbar).length === 1) {
                sb.track = s.container.find(s.params.scrollbar);
            }
            sb.drag = sb.track.find('.swiper-scrollbar-drag');
            if (sb.drag.length === 0) {
                sb.drag = $('<div class="swiper-scrollbar-drag"></div>');
                sb.track.append(sb.drag);
            }
            sb.drag[0].style.width = '';
            sb.drag[0].style.height = '';
            sb.trackSize = s.isHorizontal() ? sb.track[0].offsetWidth : sb.track[0].offsetHeight;

            sb.divider = s.size / s.virtualSize;
            sb.moveDivider = sb.divider * (sb.trackSize / s.size);
            sb.dragSize = sb.trackSize * sb.divider;

            if (s.isHorizontal()) {
                sb.drag[0].style.width = sb.dragSize + 'px';
            }
            else {
                sb.drag[0].style.height = sb.dragSize + 'px';
            }

            if (sb.divider >= 1) {
                sb.track[0].style.display = 'none';
            }
            else {
                sb.track[0].style.display = '';
            }
            if (s.params.scrollbarHide) {
                sb.track[0].style.opacity = 0;
            }
        },
        setTranslate: function () {
            if (!s.params.scrollbar) return;
            var diff;
            var sb = s.scrollbar;
            var translate = s.translate || 0;
            var newPos;

            var newSize = sb.dragSize;
            newPos = (sb.trackSize - sb.dragSize) * s.progress;
            if (s.rtl && s.isHorizontal()) {
                newPos = -newPos;
                if (newPos > 0) {
                    newSize = sb.dragSize - newPos;
                    newPos = 0;
                }
                else if (-newPos + sb.dragSize > sb.trackSize) {
                    newSize = sb.trackSize + newPos;
                }
            }
            else {
                if (newPos < 0) {
                    newSize = sb.dragSize + newPos;
                    newPos = 0;
                }
                else if (newPos + sb.dragSize > sb.trackSize) {
                    newSize = sb.trackSize - newPos;
                }
            }
            if (s.isHorizontal()) {
                if (s.support.transforms3d) {
                    sb.drag.transform('translate3d(' + (newPos) + 'px, 0, 0)');
                }
                else {
                    sb.drag.transform('translateX(' + (newPos) + 'px)');
                }
                sb.drag[0].style.width = newSize + 'px';
            }
            else {
                if (s.support.transforms3d) {
                    sb.drag.transform('translate3d(0px, ' + (newPos) + 'px, 0)');
                }
                else {
                    sb.drag.transform('translateY(' + (newPos) + 'px)');
                }
                sb.drag[0].style.height = newSize + 'px';
            }
            if (s.params.scrollbarHide) {
                clearTimeout(sb.timeout);
                sb.track[0].style.opacity = 1;
                sb.timeout = setTimeout(function () {
                    sb.track[0].style.opacity = 0;
                    sb.track.transition(400);
                }, 1000);
            }
        },
        setTransition: function (duration) {
            if (!s.params.scrollbar) return;
            s.scrollbar.drag.transition(duration);
        }
    };


    /*=========================
    Controller
    ===========================*/
    s.controller = {
        LinearSpline: function (x, y) {
            var binarySearch = (function() {
                var maxIndex, minIndex, guess;
                return function(array, val) {
                    minIndex = -1;
                    maxIndex = array.length;
                    while (maxIndex - minIndex > 1)
                        if (array[guess = maxIndex + minIndex >> 1] <= val) {
                            minIndex = guess;
                        } else {
                            maxIndex = guess;
                        }
                    return maxIndex;
                };
            })();
            this.x = x;
            this.y = y;
            this.lastIndex = x.length - 1;
            // Given an x value (x2), return the expected y2 value:
            // (x1,y1) is the known point before given value,
            // (x3,y3) is the known point after given value.
            var i1, i3;
            var l = this.x.length;

            this.interpolate = function (x2) {
                if (!x2) return 0;

                // Get the indexes of x1 and x3 (the array indexes before and after given x2):
                i3 = binarySearch(this.x, x2);
                i1 = i3 - 1;

                // We have our indexes i1 & i3, so we can calculate already:
                // y2 := ((x2−x1) × (y3−y1)) ÷ (x3−x1) + y1
                return ((x2 - this.x[i1]) * (this.y[i3] - this.y[i1])) / (this.x[i3] - this.x[i1]) + this.y[i1];
            };
        },
        //xxx: for now i will just save one spline function to to
        getInterpolateFunction: function(c){
            if(!s.controller.spline) s.controller.spline = s.params.loop ?
                new s.controller.LinearSpline(s.slidesGrid, c.slidesGrid) :
                new s.controller.LinearSpline(s.snapGrid, c.snapGrid);
        },
        setTranslate: function (translate, byController) {
            var controlled = s.params.control;
            var multiplier, controlledTranslate;
            function setControlledTranslate(c) {
                // this will create an Interpolate function based on the snapGrids
                // x is the Grid of the scrolled scroller and y will be the controlled scroller
                // it makes sense to create this only once and recall it for the interpolation
                // the function does a lot of value caching for performance
                translate = c.rtl && c.params.direction === 'horizontal' ? -s.translate : s.translate;
                if (s.params.controlBy === 'slide') {
                    s.controller.getInterpolateFunction(c);
                    // i am not sure why the values have to be multiplicated this way, tried to invert the snapGrid
                    // but it did not work out
                    controlledTranslate = -s.controller.spline.interpolate(-translate);
                }

                if(!controlledTranslate || s.params.controlBy === 'container'){
                    multiplier = (c.maxTranslate() - c.minTranslate()) / (s.maxTranslate() - s.minTranslate());
                    controlledTranslate = (translate - s.minTranslate()) * multiplier + c.minTranslate();
                }

                if (s.params.controlInverse) {
                    controlledTranslate = c.maxTranslate() - controlledTranslate;
                }
                c.updateProgress(controlledTranslate);
                c.setWrapperTranslate(controlledTranslate, false, s);
                c.updateActiveIndex();
            }
            if (Array.isArray(controlled)) {
                for (var i = 0; i < controlled.length; i++) {
                    if (controlled[i] !== byController && controlled[i] instanceof Swiper) {
                        setControlledTranslate(controlled[i]);
                    }
                }
            }
            else if (controlled instanceof Swiper && byController !== controlled) {

                setControlledTranslate(controlled);
            }
        },
        setTransition: function (duration, byController) {
            var controlled = s.params.control;
            var i;
            function setControlledTransition(c) {
                c.setWrapperTransition(duration, s);
                if (duration !== 0) {
                    c.onTransitionStart();
                    c.wrapper.transitionEnd(function(){
                        if (!controlled) return;
                        if (c.params.loop && s.params.controlBy === 'slide') {
                            c.fixLoop();
                        }
                        c.onTransitionEnd();

                    });
                }
            }
            if (Array.isArray(controlled)) {
                for (i = 0; i < controlled.length; i++) {
                    if (controlled[i] !== byController && controlled[i] instanceof Swiper) {
                        setControlledTransition(controlled[i]);
                    }
                }
            }
            else if (controlled instanceof Swiper && byController !== controlled) {
                setControlledTransition(controlled);
            }
        }
    };


    /*=========================
    Hash Navigation
    ===========================*/
    s.hashnav = {
        onHashCange: function (e, a) {
            var newHash = document.location.hash.replace('#', '');
            var activeSlideHash = s.slides.eq(s.activeIndex).attr('data-hash');
            if (newHash !== activeSlideHash) {
                s.slideTo(s.wrapper.children('.' + s.params.slideClass + '[data-hash="' + (newHash) + '"]').index());
            }
        },
        attachEvents: function (detach) {
            var action = detach ? 'off' : 'on';
            $(window)[action]('hashchange', s.hashnav.onHashCange);
        },
        setHash: function () {
            if (!s.hashnav.initialized || !s.params.hashnav) return;
            if (s.params.replaceState && window.history && window.history.replaceState) {
                window.history.replaceState(null, null, ('#' + s.slides.eq(s.activeIndex).attr('data-hash') || ''));
            } else {
                var slide = s.slides.eq(s.activeIndex);
                var hash = slide.attr('data-hash') || slide.attr('data-history');
                document.location.hash = hash || '';
            }
        },
        init: function () {
            if (!s.params.hashnav || s.params.history) return;
            s.hashnav.initialized = true;
            var hash = document.location.hash.replace('#', '');
            if (hash) {
                var speed = 0;
                for (var i = 0, length = s.slides.length; i < length; i++) {
                    var slide = s.slides.eq(i);
                    var slideHash = slide.attr('data-hash') || slide.attr('data-history');
                    if (slideHash === hash && !slide.hasClass(s.params.slideDuplicateClass)) {
                        var index = slide.index();
                        s.slideTo(index, speed, s.params.runCallbacksOnInit, true);
                    }
                }
            }
            if (s.params.hashnavWatchState) s.hashnav.attachEvents();
        },
        destroy: function () {
            if (s.params.hashnavWatchState) s.hashnav.attachEvents(true);
        }
    };


    /*=========================
    History Api with fallback to Hashnav
    ===========================*/
    s.history = {
        init: function () {
            if (!s.params.history) return;
            if (!window.history || !window.history.pushState) {
                s.params.history = false;
                s.params.hashnav = true;
                return;
            }
            s.history.initialized = true;
            this.paths = this.getPathValues();
            if (!this.paths.key && !this.paths.value) return;
            this.scrollToSlide(0, this.paths.value, s.params.runCallbacksOnInit);
            if (!s.params.replaceState) {
                window.addEventListener('popstate', this.setHistoryPopState);
            }
        },
        setHistoryPopState: function() {
            s.history.paths = s.history.getPathValues();
            s.history.scrollToSlide(s.params.speed, s.history.paths.value, false);
        },
        getPathValues: function() {
            var pathArray = window.location.pathname.slice(1).split('/');
            var total = pathArray.length;
            var key = pathArray[total - 2];
            var value = pathArray[total - 1];
            return { key: key, value: value };
        },
        setHistory: function (key, index) {
            if (!s.history.initialized || !s.params.history) return;
            var slide = s.slides.eq(index);
            var value = this.slugify(slide.attr('data-history'));
            if (!window.location.pathname.includes(key)) {
                value = key + '/' + value;
            }
            if (s.params.replaceState) {
                window.history.replaceState(null, null, value);
            } else {
                window.history.pushState(null, null, value);
            }
        },
        slugify: function(text) {
            return text.toString().toLowerCase()
                .replace(/\s+/g, '-')
                .replace(/[^\w\-]+/g, '')
                .replace(/\-\-+/g, '-')
                .replace(/^-+/, '')
                .replace(/-+$/, '');
        },
        scrollToSlide: function(speed, value, runCallbacks) {
            if (value) {
                for (var i = 0, length = s.slides.length; i < length; i++) {
                    var slide = s.slides.eq(i);
                    var slideHistory = this.slugify(slide.attr('data-history'));
                    if (slideHistory === value && !slide.hasClass(s.params.slideDuplicateClass)) {
                        var index = slide.index();
                        s.slideTo(index, speed, runCallbacks);
                    }
                }
            } else {
                s.slideTo(0, speed, runCallbacks);
            }
        }
    };


    /*=========================
    Keyboard Control
    ===========================*/
    function handleKeyboard(e) {
        if (e.originalEvent) e = e.originalEvent; //jquery fix
        var kc = e.keyCode || e.charCode;
        // Directions locks
        if (!s.params.allowSwipeToNext && (s.isHorizontal() && kc === 39 || !s.isHorizontal() && kc === 40)) {
            return false;
        }
        if (!s.params.allowSwipeToPrev && (s.isHorizontal() && kc === 37 || !s.isHorizontal() && kc === 38)) {
            return false;
        }
        if (e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) {
            return;
        }
        if (document.activeElement && document.activeElement.nodeName && (document.activeElement.nodeName.toLowerCase() === 'input' || document.activeElement.nodeName.toLowerCase() === 'textarea')) {
            return;
        }
        if (kc === 37 || kc === 39 || kc === 38 || kc === 40) {
            var inView = false;
            //Check that swiper should be inside of visible area of window
            if (s.container.parents('.' + s.params.slideClass).length > 0 && s.container.parents('.' + s.params.slideActiveClass).length === 0) {
                return;
            }
            var windowScroll = {
                left: window.pageXOffset,
                top: window.pageYOffset
            };
            var windowWidth = window.innerWidth;
            var windowHeight = window.innerHeight;
            var swiperOffset = s.container.offset();
            if (s.rtl) swiperOffset.left = swiperOffset.left - s.container[0].scrollLeft;
            var swiperCoord = [
                [swiperOffset.left, swiperOffset.top],
                [swiperOffset.left + s.width, swiperOffset.top],
                [swiperOffset.left, swiperOffset.top + s.height],
                [swiperOffset.left + s.width, swiperOffset.top + s.height]
            ];
            for (var i = 0; i < swiperCoord.length; i++) {
                var point = swiperCoord[i];
                if (
                    point[0] >= windowScroll.left && point[0] <= windowScroll.left + windowWidth &&
                    point[1] >= windowScroll.top && point[1] <= windowScroll.top + windowHeight
                ) {
                    inView = true;
                }

            }
            if (!inView) return;
        }
        if (s.isHorizontal()) {
            if (kc === 37 || kc === 39) {
                if (e.preventDefault) e.preventDefault();
                else e.returnValue = false;
            }
            if ((kc === 39 && !s.rtl) || (kc === 37 && s.rtl)) s.slideNext();
            if ((kc === 37 && !s.rtl) || (kc === 39 && s.rtl)) s.slidePrev();
        }
        else {
            if (kc === 38 || kc === 40) {
                if (e.preventDefault) e.preventDefault();
                else e.returnValue = false;
            }
            if (kc === 40) s.slideNext();
            if (kc === 38) s.slidePrev();
        }
        s.emit('onKeyPress', s, kc);
    }
    s.disableKeyboardControl = function () {
        s.params.keyboardControl = false;
        $(document).off('keydown', handleKeyboard);
    };
    s.enableKeyboardControl = function () {
          s.params.keyboardControl = true;
          $(document).on('keydown', handleKeyboard);
      };


    /*=========================
    Mousewheel Control
    ===========================*/
    s.mousewheel = {
        event: false,
        lastScrollTime: (new window.Date()).getTime()
    };
    function isEventSupported() {
        var eventName = 'onwheel';
        var isSupported = eventName in document;

        if (!isSupported) {
            var element = document.createElement('div');
            element.setAttribute(eventName, 'return;');
            isSupported = typeof element[eventName] === 'function';
        }

        if (!isSupported &&
            document.implementation &&
            document.implementation.hasFeature &&
                // always returns true in newer browsers as per the standard.
                // @see http://dom.spec.whatwg.org/#dom-domimplementation-hasfeature
            document.implementation.hasFeature('', '') !== true ) {
            // This is the only way to test support for the `wheel` event in IE9+.
            isSupported = document.implementation.hasFeature('Events.wheel', '3.0');
        }

        return isSupported;
    }
    /**
     * Mouse wheel (and 2-finger trackpad) support on the web sucks.  It is
     * complicated, thus this doc is long and (hopefully) detailed enough to answer
     * your questions.
     *
     * If you need to react to the mouse wheel in a predictable way, this code is
     * like your bestest friend. * hugs *
     *
     * As of today, there are 4 DOM event types you can listen to:
     *
     *   'wheel'                -- Chrome(31+), FF(17+), IE(9+)
     *   'mousewheel'           -- Chrome, IE(6+), Opera, Safari
     *   'MozMousePixelScroll'  -- FF(3.5 only!) (2010-2013) -- don't bother!
     *   'DOMMouseScroll'       -- FF(0.9.7+) since 2003
     *
     * So what to do?  The is the best:
     *
     *   normalizeWheel.getEventType();
     *
     * In your event callback, use this code to get sane interpretation of the
     * deltas.  This code will return an object with properties:
     *
     *   spinX   -- normalized spin speed (use for zoom) - x plane
     *   spinY   -- " - y plane
     *   pixelX  -- normalized distance (to pixels) - x plane
     *   pixelY  -- " - y plane
     *
     * Wheel values are provided by the browser assuming you are using the wheel to
     * scroll a web page by a number of lines or pixels (or pages).  Values can vary
     * significantly on different platforms and browsers, forgetting that you can
     * scroll at different speeds.  Some devices (like trackpads) emit more events
     * at smaller increments with fine granularity, and some emit massive jumps with
     * linear speed or acceleration.
     *
     * This code does its best to normalize the deltas for you:
     *
     *   - spin is trying to normalize how far the wheel was spun (or trackpad
     *     dragged).  This is super useful for zoom support where you want to
     *     throw away the chunky scroll steps on the PC and make those equal to
     *     the slow and smooth tiny steps on the Mac. Key data: This code tries to
     *     resolve a single slow step on a wheel to 1.
     *
     *   - pixel is normalizing the desired scroll delta in pixel units.  You'll
     *     get the crazy differences between browsers, but at least it'll be in
     *     pixels!
     *
     *   - positive value indicates scrolling DOWN/RIGHT, negative UP/LEFT.  This
     *     should translate to positive value zooming IN, negative zooming OUT.
     *     This matches the newer 'wheel' event.
     *
     * Why are there spinX, spinY (or pixels)?
     *
     *   - spinX is a 2-finger side drag on the trackpad, and a shift + wheel turn
     *     with a mouse.  It results in side-scrolling in the browser by default.
     *
     *   - spinY is what you expect -- it's the classic axis of a mouse wheel.
     *
     *   - I dropped spinZ/pixelZ.  It is supported by the DOM 3 'wheel' event and
     *     probably is by browsers in conjunction with fancy 3D controllers .. but
     *     you know.
     *
     * Implementation info:
     *
     * Examples of 'wheel' event if you scroll slowly (down) by one step with an
     * average mouse:
     *
     *   OS X + Chrome  (mouse)     -    4   pixel delta  (wheelDelta -120)
     *   OS X + Safari  (mouse)     -  N/A   pixel delta  (wheelDelta  -12)
     *   OS X + Firefox (mouse)     -    0.1 line  delta  (wheelDelta  N/A)
     *   Win8 + Chrome  (mouse)     -  100   pixel delta  (wheelDelta -120)
     *   Win8 + Firefox (mouse)     -    3   line  delta  (wheelDelta -120)
     *
     * On the trackpad:
     *
     *   OS X + Chrome  (trackpad)  -    2   pixel delta  (wheelDelta   -6)
     *   OS X + Firefox (trackpad)  -    1   pixel delta  (wheelDelta  N/A)
     *
     * On other/older browsers.. it's more complicated as there can be multiple and
     * also missing delta values.
     *
     * The 'wheel' event is more standard:
     *
     * http://www.w3.org/TR/DOM-Level-3-Events/#events-wheelevents
     *
     * The basics is that it includes a unit, deltaMode (pixels, lines, pages), and
     * deltaX, deltaY and deltaZ.  Some browsers provide other values to maintain
     * backward compatibility with older events.  Those other values help us
     * better normalize spin speed.  Example of what the browsers provide:
     *
     *                          | event.wheelDelta | event.detail
     *        ------------------+------------------+--------------
     *          Safari v5/OS X  |       -120       |       0
     *          Safari v5/Win7  |       -120       |       0
     *         Chrome v17/OS X  |       -120       |       0
     *         Chrome v17/Win7  |       -120       |       0
     *                IE9/Win7  |       -120       |   undefined
     *         Firefox v4/OS X  |     undefined    |       1
     *         Firefox v4/Win7  |     undefined    |       3
     *
     */
    function normalizeWheel( /*object*/ event ) /*object*/ {
        // Reasonable defaults
        var PIXEL_STEP = 10;
        var LINE_HEIGHT = 40;
        var PAGE_HEIGHT = 800;

        var sX = 0, sY = 0,       // spinX, spinY
            pX = 0, pY = 0;       // pixelX, pixelY

        // Legacy
        if( 'detail' in event ) {
            sY = event.detail;
        }
        if( 'wheelDelta' in event ) {
            sY = -event.wheelDelta / 120;
        }
        if( 'wheelDeltaY' in event ) {
            sY = -event.wheelDeltaY / 120;
        }
        if( 'wheelDeltaX' in event ) {
            sX = -event.wheelDeltaX / 120;
        }

        // side scrolling on FF with DOMMouseScroll
        if( 'axis' in event && event.axis === event.HORIZONTAL_AXIS ) {
            sX = sY;
            sY = 0;
        }

        pX = sX * PIXEL_STEP;
        pY = sY * PIXEL_STEP;

        if( 'deltaY' in event ) {
            pY = event.deltaY;
        }
        if( 'deltaX' in event ) {
            pX = event.deltaX;
        }

        if( (pX || pY) && event.deltaMode ) {
            if( event.deltaMode === 1 ) {          // delta in LINE units
                pX *= LINE_HEIGHT;
                pY *= LINE_HEIGHT;
            } else {                             // delta in PAGE units
                pX *= PAGE_HEIGHT;
                pY *= PAGE_HEIGHT;
            }
        }

        // Fall-back if spin cannot be determined
        if( pX && !sX ) {
            sX = (pX < 1) ? -1 : 1;
        }
        if( pY && !sY ) {
            sY = (pY < 1) ? -1 : 1;
        }

        return {
            spinX: sX,
            spinY: sY,
            pixelX: pX,
            pixelY: pY
        };
    }
    if (s.params.mousewheelControl) {
        /**
         * The best combination if you prefer spinX + spinY normalization.  It favors
         * the older DOMMouseScroll for Firefox, as FF does not include wheelDelta with
         * 'wheel' event, making spin speed determination impossible.
         */
        s.mousewheel.event = (navigator.userAgent.indexOf('firefox') > -1) ?
            'DOMMouseScroll' :
            isEventSupported() ?
                'wheel' : 'mousewheel';
    }
    function handleMousewheel(e) {
        if (e.originalEvent) e = e.originalEvent; //jquery fix
        var delta = 0;
        var rtlFactor = s.rtl ? -1 : 1;

        var data = normalizeWheel( e );

        if (s.params.mousewheelForceToAxis) {
            if (s.isHorizontal()) {
                if (Math.abs(data.pixelX) > Math.abs(data.pixelY)) delta = data.pixelX * rtlFactor;
                else return;
            }
            else {
                if (Math.abs(data.pixelY) > Math.abs(data.pixelX)) delta = data.pixelY;
                else return;
            }
        }
        else {
            delta = Math.abs(data.pixelX) > Math.abs(data.pixelY) ? - data.pixelX * rtlFactor : - data.pixelY;
        }

        if (delta === 0) return;

        if (s.params.mousewheelInvert) delta = -delta;

        if (!s.params.freeMode) {
            if ((new window.Date()).getTime() - s.mousewheel.lastScrollTime > 60) {
                if (delta < 0) {
                    if ((!s.isEnd || s.params.loop) && !s.animating) {
                        s.slideNext();
                        s.emit('onScroll', s, e);
                    }
                    else if (s.params.mousewheelReleaseOnEdges) return true;
                }
                else {
                    if ((!s.isBeginning || s.params.loop) && !s.animating) {
                        s.slidePrev();
                        s.emit('onScroll', s, e);
                    }
                    else if (s.params.mousewheelReleaseOnEdges) return true;
                }
            }
            s.mousewheel.lastScrollTime = (new window.Date()).getTime();

        }
        else {
            //Freemode or scrollContainer:
            var position = s.getWrapperTranslate() + delta * s.params.mousewheelSensitivity;
            var wasBeginning = s.isBeginning,
                wasEnd = s.isEnd;

            if (position >= s.minTranslate()) position = s.minTranslate();
            if (position <= s.maxTranslate()) position = s.maxTranslate();

            s.setWrapperTransition(0);
            s.setWrapperTranslate(position);
            s.updateProgress();
            s.updateActiveIndex();

            if (!wasBeginning && s.isBeginning || !wasEnd && s.isEnd) {
                s.updateClasses();
            }

            if (s.params.freeModeSticky) {
                clearTimeout(s.mousewheel.timeout);
                s.mousewheel.timeout = setTimeout(function () {
                    s.slideReset();
                }, 300);
            }
            else {
                if (s.params.lazyLoading && s.lazy) {
                    s.lazy.load();
                }
            }
            // Emit event
            s.emit('onScroll', s, e);

            // Stop autoplay
            if (s.params.autoplay && s.params.autoplayDisableOnInteraction) s.stopAutoplay();

            // Return page scroll on edge positions
            if (position === 0 || position === s.maxTranslate()) return;
        }

        if (e.preventDefault) e.preventDefault();
        else e.returnValue = false;
        return false;
    }
    s.disableMousewheelControl = function () {
        if (!s.mousewheel.event) return false;
        var target = s.container;
        if (s.params.mousewheelEventsTarged !== 'container') {
            target = $(s.params.mousewheelEventsTarged);
        }
        target.off(s.mousewheel.event, handleMousewheel);
        s.params.mousewheelControl = false;
        return true;
    };

    s.enableMousewheelControl = function () {
        if (!s.mousewheel.event) return false;
        var target = s.container;
        if (s.params.mousewheelEventsTarged !== 'container') {
            target = $(s.params.mousewheelEventsTarged);
        }
        target.on(s.mousewheel.event, handleMousewheel);
        s.params.mousewheelControl = true;
        return true;
    };


    /*=========================
    Parallax
    ===========================*/
    function setParallaxTransform(el, progress) {
        el = $(el);
        var p, pX, pY;
        var rtlFactor = s.rtl ? -1 : 1;

        p = el.attr('data-swiper-parallax') || '0';
        pX = el.attr('data-swiper-parallax-x');
        pY = el.attr('data-swiper-parallax-y');
        if (pX || pY) {
            pX = pX || '0';
            pY = pY || '0';
        }
        else {
            if (s.isHorizontal()) {
                pX = p;
                pY = '0';
            }
            else {
                pY = p;
                pX = '0';
            }
        }

        if ((pX).indexOf('%') >= 0) {
            pX = parseInt(pX, 10) * progress * rtlFactor + '%';
        }
        else {
            pX = pX * progress * rtlFactor + 'px' ;
        }
        if ((pY).indexOf('%') >= 0) {
            pY = parseInt(pY, 10) * progress + '%';
        }
        else {
            pY = pY * progress + 'px' ;
        }

        el.transform('translate3d(' + pX + ', ' + pY + ',0px)');
    }
    s.parallax = {
        setTranslate: function () {
            s.container.children('[data-swiper-parallax], [data-swiper-parallax-x], [data-swiper-parallax-y]').each(function(){
                setParallaxTransform(this, s.progress);

            });
            s.slides.each(function () {
                var slide = $(this);
                slide.find('[data-swiper-parallax], [data-swiper-parallax-x], [data-swiper-parallax-y]').each(function () {
                    var progress = Math.min(Math.max(slide[0].progress, -1), 1);
                    setParallaxTransform(this, progress);
                });
            });
        },
        setTransition: function (duration) {
            if (typeof duration === 'undefined') duration = s.params.speed;
            s.container.find('[data-swiper-parallax], [data-swiper-parallax-x], [data-swiper-parallax-y]').each(function(){
                var el = $(this);
                var parallaxDuration = parseInt(el.attr('data-swiper-parallax-duration'), 10) || duration;
                if (duration === 0) parallaxDuration = 0;
                el.transition(parallaxDuration);
            });
        }
    };


    /*=========================
    Zoom
    ===========================*/
    s.zoom = {
        // "Global" Props
        scale: 1,
        currentScale: 1,
        isScaling: false,
        gesture: {
            slide: undefined,
            slideWidth: undefined,
            slideHeight: undefined,
            image: undefined,
            imageWrap: undefined,
            zoomMax: s.params.zoomMax
        },
        image: {
            isTouched: undefined,
            isMoved: undefined,
            currentX: undefined,
            currentY: undefined,
            minX: undefined,
            minY: undefined,
            maxX: undefined,
            maxY: undefined,
            width: undefined,
            height: undefined,
            startX: undefined,
            startY: undefined,
            touchesStart: {},
            touchesCurrent: {}
        },
        velocity: {
            x: undefined,
            y: undefined,
            prevPositionX: undefined,
            prevPositionY: undefined,
            prevTime: undefined
        },
        // Calc Scale From Multi-touches
        getDistanceBetweenTouches: function (e) {
            if (e.targetTouches.length < 2) return 1;
            var x1 = e.targetTouches[0].pageX,
                y1 = e.targetTouches[0].pageY,
                x2 = e.targetTouches[1].pageX,
                y2 = e.targetTouches[1].pageY;
            var distance = Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2));
            return distance;
        },
        // Events
        onGestureStart: function (e) {
            var z = s.zoom;
            if (!s.support.gestures) {
                if (e.type !== 'touchstart' || e.type === 'touchstart' && e.targetTouches.length < 2) {
                    return;
                }
                z.gesture.scaleStart = z.getDistanceBetweenTouches(e);
            }
            if (!z.gesture.slide || !z.gesture.slide.length) {
                z.gesture.slide = $(this);
                if (z.gesture.slide.length === 0) z.gesture.slide = s.slides.eq(s.activeIndex);
                z.gesture.image = z.gesture.slide.find('img, svg, canvas');
                z.gesture.imageWrap = z.gesture.image.parent('.' + s.params.zoomContainerClass);
                z.gesture.zoomMax = z.gesture.imageWrap.attr('data-swiper-zoom') || s.params.zoomMax ;
                if (z.gesture.imageWrap.length === 0) {
                    z.gesture.image = undefined;
                    return;
                }
            }
            z.gesture.image.transition(0);
            z.isScaling = true;
        },
        onGestureChange: function (e) {
            var z = s.zoom;
            if (!s.support.gestures) {
                if (e.type !== 'touchmove' || e.type === 'touchmove' && e.targetTouches.length < 2) {
                    return;
                }
                z.gesture.scaleMove = z.getDistanceBetweenTouches(e);
            }
            if (!z.gesture.image || z.gesture.image.length === 0) return;
            if (s.support.gestures) {
                z.scale = e.scale * z.currentScale;
            }
            else {
                z.scale = (z.gesture.scaleMove / z.gesture.scaleStart) * z.currentScale;
            }
            if (z.scale > z.gesture.zoomMax) {
                z.scale = z.gesture.zoomMax - 1 + Math.pow((z.scale - z.gesture.zoomMax + 1), 0.5);
            }
            if (z.scale < s.params.zoomMin) {
                z.scale =  s.params.zoomMin + 1 - Math.pow((s.params.zoomMin - z.scale + 1), 0.5);
            }
            z.gesture.image.transform('translate3d(0,0,0) scale(' + z.scale + ')');
        },
        onGestureEnd: function (e) {
            var z = s.zoom;
            if (!s.support.gestures) {
                if (e.type !== 'touchend' || e.type === 'touchend' && e.changedTouches.length < 2) {
                    return;
                }
            }
            if (!z.gesture.image || z.gesture.image.length === 0) return;
            z.scale = Math.max(Math.min(z.scale, z.gesture.zoomMax), s.params.zoomMin);
            z.gesture.image.transition(s.params.speed).transform('translate3d(0,0,0) scale(' + z.scale + ')');
            z.currentScale = z.scale;
            z.isScaling = false;
            if (z.scale === 1) z.gesture.slide = undefined;
        },
        onTouchStart: function (s, e) {
            var z = s.zoom;
            if (!z.gesture.image || z.gesture.image.length === 0) return;
            if (z.image.isTouched) return;
            if (s.device.os === 'android') e.preventDefault();
            z.image.isTouched = true;
            z.image.touchesStart.x = e.type === 'touchstart' ? e.targetTouches[0].pageX : e.pageX;
            z.image.touchesStart.y = e.type === 'touchstart' ? e.targetTouches[0].pageY : e.pageY;
        },
        onTouchMove: function (e) {
            var z = s.zoom;
            if (!z.gesture.image || z.gesture.image.length === 0) return;
            s.allowClick = false;
            if (!z.image.isTouched || !z.gesture.slide) return;

            if (!z.image.isMoved) {
                z.image.width = z.gesture.image[0].offsetWidth;
                z.image.height = z.gesture.image[0].offsetHeight;
                z.image.startX = s.getTranslate(z.gesture.imageWrap[0], 'x') || 0;
                z.image.startY = s.getTranslate(z.gesture.imageWrap[0], 'y') || 0;
                z.gesture.slideWidth = z.gesture.slide[0].offsetWidth;
                z.gesture.slideHeight = z.gesture.slide[0].offsetHeight;
                z.gesture.imageWrap.transition(0);
                if (s.rtl) z.image.startX = -z.image.startX;
                if (s.rtl) z.image.startY = -z.image.startY;
            }
            // Define if we need image drag
            var scaledWidth = z.image.width * z.scale;
            var scaledHeight = z.image.height * z.scale;

            if (scaledWidth < z.gesture.slideWidth && scaledHeight < z.gesture.slideHeight) return;

            z.image.minX = Math.min((z.gesture.slideWidth / 2 - scaledWidth / 2), 0);
            z.image.maxX = -z.image.minX;
            z.image.minY = Math.min((z.gesture.slideHeight / 2 - scaledHeight / 2), 0);
            z.image.maxY = -z.image.minY;

            z.image.touchesCurrent.x = e.type === 'touchmove' ? e.targetTouches[0].pageX : e.pageX;
            z.image.touchesCurrent.y = e.type === 'touchmove' ? e.targetTouches[0].pageY : e.pageY;

            if (!z.image.isMoved && !z.isScaling) {
                if (s.isHorizontal() &&
                    (Math.floor(z.image.minX) === Math.floor(z.image.startX) && z.image.touchesCurrent.x < z.image.touchesStart.x) ||
                    (Math.floor(z.image.maxX) === Math.floor(z.image.startX) && z.image.touchesCurrent.x > z.image.touchesStart.x)
                    ) {
                    z.image.isTouched = false;
                    return;
                }
                else if (!s.isHorizontal() &&
                    (Math.floor(z.image.minY) === Math.floor(z.image.startY) && z.image.touchesCurrent.y < z.image.touchesStart.y) ||
                    (Math.floor(z.image.maxY) === Math.floor(z.image.startY) && z.image.touchesCurrent.y > z.image.touchesStart.y)
                    ) {
                    z.image.isTouched = false;
                    return;
                }
            }
            e.preventDefault();
            e.stopPropagation();

            z.image.isMoved = true;
            z.image.currentX = z.image.touchesCurrent.x - z.image.touchesStart.x + z.image.startX;
            z.image.currentY = z.image.touchesCurrent.y - z.image.touchesStart.y + z.image.startY;

            if (z.image.currentX < z.image.minX) {
                z.image.currentX =  z.image.minX + 1 - Math.pow((z.image.minX - z.image.currentX + 1), 0.8);
            }
            if (z.image.currentX > z.image.maxX) {
                z.image.currentX = z.image.maxX - 1 + Math.pow((z.image.currentX - z.image.maxX + 1), 0.8);
            }

            if (z.image.currentY < z.image.minY) {
                z.image.currentY =  z.image.minY + 1 - Math.pow((z.image.minY - z.image.currentY + 1), 0.8);
            }
            if (z.image.currentY > z.image.maxY) {
                z.image.currentY = z.image.maxY - 1 + Math.pow((z.image.currentY - z.image.maxY + 1), 0.8);
            }

            //Velocity
            if (!z.velocity.prevPositionX) z.velocity.prevPositionX = z.image.touchesCurrent.x;
            if (!z.velocity.prevPositionY) z.velocity.prevPositionY = z.image.touchesCurrent.y;
            if (!z.velocity.prevTime) z.velocity.prevTime = Date.now();
            z.velocity.x = (z.image.touchesCurrent.x - z.velocity.prevPositionX) / (Date.now() - z.velocity.prevTime) / 2;
            z.velocity.y = (z.image.touchesCurrent.y - z.velocity.prevPositionY) / (Date.now() - z.velocity.prevTime) / 2;
            if (Math.abs(z.image.touchesCurrent.x - z.velocity.prevPositionX) < 2) z.velocity.x = 0;
            if (Math.abs(z.image.touchesCurrent.y - z.velocity.prevPositionY) < 2) z.velocity.y = 0;
            z.velocity.prevPositionX = z.image.touchesCurrent.x;
            z.velocity.prevPositionY = z.image.touchesCurrent.y;
            z.velocity.prevTime = Date.now();

            z.gesture.imageWrap.transform('translate3d(' + z.image.currentX + 'px, ' + z.image.currentY + 'px,0)');
        },
        onTouchEnd: function (s, e) {
            var z = s.zoom;
            if (!z.gesture.image || z.gesture.image.length === 0) return;
            if (!z.image.isTouched || !z.image.isMoved) {
                z.image.isTouched = false;
                z.image.isMoved = false;
                return;
            }
            z.image.isTouched = false;
            z.image.isMoved = false;
            var momentumDurationX = 300;
            var momentumDurationY = 300;
            var momentumDistanceX = z.velocity.x * momentumDurationX;
            var newPositionX = z.image.currentX + momentumDistanceX;
            var momentumDistanceY = z.velocity.y * momentumDurationY;
            var newPositionY = z.image.currentY + momentumDistanceY;

            //Fix duration
            if (z.velocity.x !== 0) momentumDurationX = Math.abs((newPositionX - z.image.currentX) / z.velocity.x);
            if (z.velocity.y !== 0) momentumDurationY = Math.abs((newPositionY - z.image.currentY) / z.velocity.y);
            var momentumDuration = Math.max(momentumDurationX, momentumDurationY);

            z.image.currentX = newPositionX;
            z.image.currentY = newPositionY;

            // Define if we need image drag
            var scaledWidth = z.image.width * z.scale;
            var scaledHeight = z.image.height * z.scale;
            z.image.minX = Math.min((z.gesture.slideWidth / 2 - scaledWidth / 2), 0);
            z.image.maxX = -z.image.minX;
            z.image.minY = Math.min((z.gesture.slideHeight / 2 - scaledHeight / 2), 0);
            z.image.maxY = -z.image.minY;
            z.image.currentX = Math.max(Math.min(z.image.currentX, z.image.maxX), z.image.minX);
            z.image.currentY = Math.max(Math.min(z.image.currentY, z.image.maxY), z.image.minY);

            z.gesture.imageWrap.transition(momentumDuration).transform('translate3d(' + z.image.currentX + 'px, ' + z.image.currentY + 'px,0)');
        },
        onTransitionEnd: function (s) {
            var z = s.zoom;
            if (z.gesture.slide && s.previousIndex !== s.activeIndex) {
                z.gesture.image.transform('translate3d(0,0,0) scale(1)');
                z.gesture.imageWrap.transform('translate3d(0,0,0)');
                z.gesture.slide = z.gesture.image = z.gesture.imageWrap = undefined;
                z.scale = z.currentScale = 1;
            }
        },
        // Toggle Zoom
        toggleZoom: function (s, e) {
            var z = s.zoom;
            if (!z.gesture.slide) {
                z.gesture.slide = s.clickedSlide ? $(s.clickedSlide) : s.slides.eq(s.activeIndex);
                z.gesture.image = z.gesture.slide.find('img, svg, canvas');
                z.gesture.imageWrap = z.gesture.image.parent('.' + s.params.zoomContainerClass);
            }
            if (!z.gesture.image || z.gesture.image.length === 0) return;

            var touchX, touchY, offsetX, offsetY, diffX, diffY, translateX, translateY, imageWidth, imageHeight, scaledWidth, scaledHeight, translateMinX, translateMinY, translateMaxX, translateMaxY, slideWidth, slideHeight;

            if (typeof z.image.touchesStart.x === 'undefined' && e) {
                touchX = e.type === 'touchend' ? e.changedTouches[0].pageX : e.pageX;
                touchY = e.type === 'touchend' ? e.changedTouches[0].pageY : e.pageY;
            }
            else {
                touchX = z.image.touchesStart.x;
                touchY = z.image.touchesStart.y;
            }

            if (z.scale && z.scale !== 1) {
                // Zoom Out
                z.scale = z.currentScale = 1;
                z.gesture.imageWrap.transition(300).transform('translate3d(0,0,0)');
                z.gesture.image.transition(300).transform('translate3d(0,0,0) scale(1)');
                z.gesture.slide = undefined;
            }
            else {
                // Zoom In
                z.scale = z.currentScale = z.gesture.imageWrap.attr('data-swiper-zoom') || s.params.zoomMax;
                if (e) {
                    slideWidth = z.gesture.slide[0].offsetWidth;
                    slideHeight = z.gesture.slide[0].offsetHeight;
                    offsetX = z.gesture.slide.offset().left;
                    offsetY = z.gesture.slide.offset().top;
                    diffX = offsetX + slideWidth/2 - touchX;
                    diffY = offsetY + slideHeight/2 - touchY;

                    imageWidth = z.gesture.image[0].offsetWidth;
                    imageHeight = z.gesture.image[0].offsetHeight;
                    scaledWidth = imageWidth * z.scale;
                    scaledHeight = imageHeight * z.scale;

                    translateMinX = Math.min((slideWidth / 2 - scaledWidth / 2), 0);
                    translateMinY = Math.min((slideHeight / 2 - scaledHeight / 2), 0);
                    translateMaxX = -translateMinX;
                    translateMaxY = -translateMinY;

                    translateX = diffX * z.scale;
                    translateY = diffY * z.scale;

                    if (translateX < translateMinX) {
                        translateX =  translateMinX;
                    }
                    if (translateX > translateMaxX) {
                        translateX = translateMaxX;
                    }

                    if (translateY < translateMinY) {
                        translateY =  translateMinY;
                    }
                    if (translateY > translateMaxY) {
                        translateY = translateMaxY;
                    }
                }
                else {
                    translateX = 0;
                    translateY = 0;
                }
                z.gesture.imageWrap.transition(300).transform('translate3d(' + translateX + 'px, ' + translateY + 'px,0)');
                z.gesture.image.transition(300).transform('translate3d(0,0,0) scale(' + z.scale + ')');
            }
        },
        // Attach/Detach Events
        attachEvents: function (detach) {
            var action = detach ? 'off' : 'on';

            if (s.params.zoom) {
                var target = s.slides;
                var passiveListener = s.touchEvents.start === 'touchstart' && s.support.passiveListener && s.params.passiveListeners ? {passive: true, capture: false} : false;
                // Scale image
                if (s.support.gestures) {
                    s.slides[action]('gesturestart', s.zoom.onGestureStart, passiveListener);
                    s.slides[action]('gesturechange', s.zoom.onGestureChange, passiveListener);
                    s.slides[action]('gestureend', s.zoom.onGestureEnd, passiveListener);
                }
                else if (s.touchEvents.start === 'touchstart') {
                    s.slides[action](s.touchEvents.start, s.zoom.onGestureStart, passiveListener);
                    s.slides[action](s.touchEvents.move, s.zoom.onGestureChange, passiveListener);
                    s.slides[action](s.touchEvents.end, s.zoom.onGestureEnd, passiveListener);
                }

                // Move image
                s[action]('touchStart', s.zoom.onTouchStart);
                s.slides.each(function (index, slide){
                    if ($(slide).find('.' + s.params.zoomContainerClass).length > 0) {
                        $(slide)[action](s.touchEvents.move, s.zoom.onTouchMove);
                    }
                });
                s[action]('touchEnd', s.zoom.onTouchEnd);

                // Scale Out
                s[action]('transitionEnd', s.zoom.onTransitionEnd);
                if (s.params.zoomToggle) {
                    s.on('doubleTap', s.zoom.toggleZoom);
                }
            }
        },
        init: function () {
            s.zoom.attachEvents();
        },
        destroy: function () {
            s.zoom.attachEvents(true);
        }
    };


    /*=========================
    Plugins API. Collect all and init all plugins
    ===========================*/
    s._plugins = [];
    for (var plugin in s.plugins) {
        var p = s.plugins[plugin](s, s.params[plugin]);
        if (p) s._plugins.push(p);
    }
    // Method to call all plugins event/method
    s.callPlugins = function (eventName) {
        for (var i = 0; i < s._plugins.length; i++) {
            if (eventName in s._plugins[i]) {
                s._plugins[i][eventName](arguments[1], arguments[2], arguments[3], arguments[4], arguments[5]);
            }
        }
    };


    /*=========================
    Events/Callbacks/Plugins Emitter
    ===========================*/
    function normalizeEventName (eventName) {
        if (eventName.indexOf('on') !== 0) {
            if (eventName[0] !== eventName[0].toUpperCase()) {
                eventName = 'on' + eventName[0].toUpperCase() + eventName.substring(1);
            }
            else {
                eventName = 'on' + eventName;
            }
        }
        return eventName;
    }
    s.emitterEventListeners = {

    };
    s.emit = function (eventName) {
        // Trigger callbacks
        if (s.params[eventName]) {
            s.params[eventName](arguments[1], arguments[2], arguments[3], arguments[4], arguments[5]);
        }
        var i;
        // Trigger events
        if (s.emitterEventListeners[eventName]) {
            for (i = 0; i < s.emitterEventListeners[eventName].length; i++) {
                s.emitterEventListeners[eventName][i](arguments[1], arguments[2], arguments[3], arguments[4], arguments[5]);
            }
        }
        // Trigger plugins
        if (s.callPlugins) s.callPlugins(eventName, arguments[1], arguments[2], arguments[3], arguments[4], arguments[5]);
    };
    s.on = function (eventName, handler) {
        eventName = normalizeEventName(eventName);
        if (!s.emitterEventListeners[eventName]) s.emitterEventListeners[eventName] = [];
        s.emitterEventListeners[eventName].push(handler);
        return s;
    };
    s.off = function (eventName, handler) {
        var i;
        eventName = normalizeEventName(eventName);
        if (typeof handler === 'undefined') {
            // Remove all handlers for such event
            s.emitterEventListeners[eventName] = [];
            return s;
        }
        if (!s.emitterEventListeners[eventName] || s.emitterEventListeners[eventName].length === 0) return;
        for (i = 0; i < s.emitterEventListeners[eventName].length; i++) {
            if(s.emitterEventListeners[eventName][i] === handler) s.emitterEventListeners[eventName].splice(i, 1);
        }
        return s;
    };
    s.once = function (eventName, handler) {
        eventName = normalizeEventName(eventName);
        var _handler = function () {
            handler(arguments[0], arguments[1], arguments[2], arguments[3], arguments[4]);
            s.off(eventName, _handler);
        };
        s.on(eventName, _handler);
        return s;
    };


    // Accessibility tools
    s.a11y = {
        makeFocusable: function ($el) {
            $el.attr('tabIndex', '0');
            return $el;
        },
        addRole: function ($el, role) {
            $el.attr('role', role);
            return $el;
        },

        addLabel: function ($el, label) {
            $el.attr('aria-label', label);
            return $el;
        },

        disable: function ($el) {
            $el.attr('aria-disabled', true);
            return $el;
        },

        enable: function ($el) {
            $el.attr('aria-disabled', false);
            return $el;
        },

        onEnterKey: function (event) {
            if (event.keyCode !== 13) return;
            if ($(event.target).is(s.params.nextButton)) {
                s.onClickNext(event);
                if (s.isEnd) {
                    s.a11y.notify(s.params.lastSlideMessage);
                }
                else {
                    s.a11y.notify(s.params.nextSlideMessage);
                }
            }
            else if ($(event.target).is(s.params.prevButton)) {
                s.onClickPrev(event);
                if (s.isBeginning) {
                    s.a11y.notify(s.params.firstSlideMessage);
                }
                else {
                    s.a11y.notify(s.params.prevSlideMessage);
                }
            }
            if ($(event.target).is('.' + s.params.bulletClass)) {
                $(event.target)[0].click();
            }
        },

        liveRegion: $('<span class="' + s.params.notificationClass + '" aria-live="assertive" aria-atomic="true"></span>'),

        notify: function (message) {
            var notification = s.a11y.liveRegion;
            if (notification.length === 0) return;
            notification.html('');
            notification.html(message);
        },
        init: function () {
            // Setup accessibility
            if (s.params.nextButton && s.nextButton && s.nextButton.length > 0) {
                s.a11y.makeFocusable(s.nextButton);
                s.a11y.addRole(s.nextButton, 'button');
                s.a11y.addLabel(s.nextButton, s.params.nextSlideMessage);
            }
            if (s.params.prevButton && s.prevButton && s.prevButton.length > 0) {
                s.a11y.makeFocusable(s.prevButton);
                s.a11y.addRole(s.prevButton, 'button');
                s.a11y.addLabel(s.prevButton, s.params.prevSlideMessage);
            }

            $(s.container).append(s.a11y.liveRegion);
        },
        initPagination: function () {
            if (s.params.pagination && s.params.paginationClickable && s.bullets && s.bullets.length) {
                s.bullets.each(function () {
                    var bullet = $(this);
                    s.a11y.makeFocusable(bullet);
                    s.a11y.addRole(bullet, 'button');
                    s.a11y.addLabel(bullet, s.params.paginationBulletMessage.replace(/{{index}}/, bullet.index() + 1));
                });
            }
        },
        destroy: function () {
            if (s.a11y.liveRegion && s.a11y.liveRegion.length > 0) s.a11y.liveRegion.remove();
        }
    };


    /*=========================
    Init/Destroy
    ===========================*/
    s.init = function () {
        if (s.params.loop) s.createLoop();
        s.updateContainerSize();
        s.updateSlidesSize();
        s.updatePagination();
        if (s.params.scrollbar && s.scrollbar) {
            s.scrollbar.set();
            if (s.params.scrollbarDraggable) {
                s.scrollbar.enableDraggable();
            }
        }
        if (s.params.effect !== 'slide' && s.effects[s.params.effect]) {
            if (!s.params.loop) s.updateProgress();
            s.effects[s.params.effect].setTranslate();
        }
        if (s.params.loop) {
            s.slideTo(s.params.initialSlide + s.loopedSlides, 0, s.params.runCallbacksOnInit);
        }
        else {
            s.slideTo(s.params.initialSlide, 0, s.params.runCallbacksOnInit);
            if (s.params.initialSlide === 0) {
                if (s.parallax && s.params.parallax) s.parallax.setTranslate();
                if (s.lazy && s.params.lazyLoading) {
                    s.lazy.load();
                    s.lazy.initialImageLoaded = true;
                }
            }
        }
        s.attachEvents();
        if (s.params.observer && s.support.observer) {
            s.initObservers();
        }
        if (s.params.preloadImages && !s.params.lazyLoading) {
            s.preloadImages();
        }
        if (s.params.zoom && s.zoom) {
            s.zoom.init();
        }
        if (s.params.autoplay) {
            s.startAutoplay();
        }
        if (s.params.keyboardControl) {
            if (s.enableKeyboardControl) s.enableKeyboardControl();
        }
        if (s.params.mousewheelControl) {
            if (s.enableMousewheelControl) s.enableMousewheelControl();
        }
        // Deprecated hashnavReplaceState changed to replaceState for use in hashnav and history
        if (s.params.hashnavReplaceState) {
            s.params.replaceState = s.params.hashnavReplaceState;
        }
        if (s.params.history) {
            if (s.history) s.history.init();
        }
        if (s.params.hashnav) {
            if (s.hashnav) s.hashnav.init();
        }
        if (s.params.a11y && s.a11y) s.a11y.init();
        s.emit('onInit', s);
    };

    // Cleanup dynamic styles
    s.cleanupStyles = function () {
        // Container
        s.container.removeClass(s.classNames.join(' ')).removeAttr('style');

        // Wrapper
        s.wrapper.removeAttr('style');

        // Slides
        if (s.slides && s.slides.length) {
            s.slides
                .removeClass([
                s.params.slideVisibleClass,
                s.params.slideActiveClass,
                s.params.slideNextClass,
                s.params.slidePrevClass
                ].join(' '))
                .removeAttr('style')
                .removeAttr('data-swiper-column')
                .removeAttr('data-swiper-row');
        }

        // Pagination/Bullets
        if (s.paginationContainer && s.paginationContainer.length) {
            s.paginationContainer.removeClass(s.params.paginationHiddenClass);
        }
        if (s.bullets && s.bullets.length) {
            s.bullets.removeClass(s.params.bulletActiveClass);
        }

        // Buttons
        if (s.params.prevButton) $(s.params.prevButton).removeClass(s.params.buttonDisabledClass);
        if (s.params.nextButton) $(s.params.nextButton).removeClass(s.params.buttonDisabledClass);

        // Scrollbar
        if (s.params.scrollbar && s.scrollbar) {
            if (s.scrollbar.track && s.scrollbar.track.length) s.scrollbar.track.removeAttr('style');
            if (s.scrollbar.drag && s.scrollbar.drag.length) s.scrollbar.drag.removeAttr('style');
        }
    };

    // Destroy
    s.destroy = function (deleteInstance, cleanupStyles) {
        // Detach evebts
        s.detachEvents();
        // Stop autoplay
        s.stopAutoplay();
        // Disable draggable
        if (s.params.scrollbar && s.scrollbar) {
            if (s.params.scrollbarDraggable) {
                s.scrollbar.disableDraggable();
            }
        }
        // Destroy loop
        if (s.params.loop) {
            s.destroyLoop();
        }
        // Cleanup styles
        if (cleanupStyles) {
            s.cleanupStyles();
        }
        // Disconnect observer
        s.disconnectObservers();

        // Destroy zoom
        if (s.params.zoom && s.zoom) {
            s.zoom.destroy();
        }
        // Disable keyboard/mousewheel
        if (s.params.keyboardControl) {
            if (s.disableKeyboardControl) s.disableKeyboardControl();
        }
        if (s.params.mousewheelControl) {
            if (s.disableMousewheelControl) s.disableMousewheelControl();
        }
        // Disable a11y
        if (s.params.a11y && s.a11y) s.a11y.destroy();
        // Delete history popstate
        if (s.params.history && !s.params.replaceState) {
            window.removeEventListener('popstate', s.history.setHistoryPopState);
        }
        if (s.params.hashnav && s.hashnav)  {
            s.hashnav.destroy();
        }
        // Destroy callback
        s.emit('onDestroy');
        // Delete instance
        if (deleteInstance !== false) s = null;
    };

    s.init();



    // Return swiper instance
    return s;
  };


    /*==================================================
        Prototype
    ====================================================*/
    Swiper.prototype = {
        isSafari: (function () {
            var ua = window.navigator.userAgent.toLowerCase();
            return (ua.indexOf('safari') >= 0 && ua.indexOf('chrome') < 0 && ua.indexOf('android') < 0);
        })(),
        isUiWebView: /(iPhone|iPod|iPad).*AppleWebKit(?!.*Safari)/i.test(window.navigator.userAgent),
        isArray: function (arr) {
            return Object.prototype.toString.apply(arr) === '[object Array]';
        },
        /*==================================================
        Browser
        ====================================================*/
        browser: {
            ie: window.navigator.pointerEnabled || window.navigator.msPointerEnabled,
            ieTouch: (window.navigator.msPointerEnabled && window.navigator.msMaxTouchPoints > 1) || (window.navigator.pointerEnabled && window.navigator.maxTouchPoints > 1),
            lteIE9: (function() {
                // create temporary DIV
                var div = document.createElement('div');
                // add content to tmp DIV which is wrapped into the IE HTML conditional statement
                div.innerHTML = '<!--[if lte IE 9]><i></i><![endif]-->';
                // return true / false value based on what will browser render
                return div.getElementsByTagName('i').length === 1;
            })()
        },
        /*==================================================
        Devices
        ====================================================*/
        device: (function () {
            var ua = window.navigator.userAgent;
            var android = ua.match(/(Android);?[\s\/]+([\d.]+)?/);
            var ipad = ua.match(/(iPad).*OS\s([\d_]+)/);
            var ipod = ua.match(/(iPod)(.*OS\s([\d_]+))?/);
            var iphone = !ipad && ua.match(/(iPhone\sOS|iOS)\s([\d_]+)/);
            return {
                ios: ipad || iphone || ipod,
                android: android
            };
        })(),
        /*==================================================
        Feature Detection
        ====================================================*/
        support: {
            touch : (window.Modernizr && Modernizr.touch === true) || (function () {
                return !!(('ontouchstart' in window) || window.DocumentTouch && document instanceof DocumentTouch);
            })(),

            transforms3d : (window.Modernizr && Modernizr.csstransforms3d === true) || (function () {
                var div = document.createElement('div').style;
                return ('webkitPerspective' in div || 'MozPerspective' in div || 'OPerspective' in div || 'MsPerspective' in div || 'perspective' in div);
            })(),

            flexbox: (function () {
                var div = document.createElement('div').style;
                var styles = ('alignItems webkitAlignItems webkitBoxAlign msFlexAlign mozBoxAlign webkitFlexDirection msFlexDirection mozBoxDirection mozBoxOrient webkitBoxDirection webkitBoxOrient').split(' ');
                for (var i = 0; i < styles.length; i++) {
                    if (styles[i] in div) return true;
                }
            })(),

            observer: (function () {
                return ('MutationObserver' in window || 'WebkitMutationObserver' in window);
            })(),

            passiveListener: (function () {
                var supportsPassive = false;
                try {
                    var opts = Object.defineProperty({}, 'passive', {
                        get: function() {
                            supportsPassive = true;
                        }
                    });
                    window.addEventListener('testPassiveListener', null, opts);
                } catch (e) {}
                return supportsPassive;
            })(),

            gestures: (function () {
                return 'ongesturestart' in window;
            })()
        },
        /*==================================================
        Plugins
        ====================================================*/
        plugins: {}
    };


  /*===========================
   Get Dom libraries
   ===========================*/
  var swiperDomPlugins = ['jQuery', 'Zepto', 'Dom7'];
  for (var i = 0; i < swiperDomPlugins.length; i++) {
    if (window[swiperDomPlugins[i]]) {
      addLibraryPlugin(window[swiperDomPlugins[i]]);
    }
  }
  // Required DOM Plugins
  var domLib;
  if (typeof Dom7 === 'undefined') {
    domLib = window.Dom7 || window.Zepto || window.jQuery;
  }
  else {
    domLib = Dom7;
  }


  /*===========================
  Add .swiper plugin from Dom libraries
  ===========================*/
  function addLibraryPlugin(lib) {
      lib.fn.swiper = function (params) {
          var firstInstance;
          lib(this).each(function () {
              var s = new Swiper(this, params);
              if (!firstInstance) firstInstance = s;
          });
          return firstInstance;
      };
  }

  if (domLib) {
      if (!('transitionEnd' in domLib.fn)) {
          domLib.fn.transitionEnd = function (callback) {
              var events = ['webkitTransitionEnd', 'transitionend', 'oTransitionEnd', 'MSTransitionEnd', 'msTransitionEnd'],
                  i, j, dom = this;
              function fireCallBack(e) {
                  /*jshint validthis:true */
                  if (e.target !== this) return;
                  callback.call(this, e);
                  for (i = 0; i < events.length; i++) {
                      dom.off(events[i], fireCallBack);
                  }
              }
              if (callback) {
                  for (i = 0; i < events.length; i++) {
                      dom.on(events[i], fireCallBack);
                  }
              }
              return this;
          };
      }
      if (!('transform' in domLib.fn)) {
          domLib.fn.transform = function (transform) {
              for (var i = 0; i < this.length; i++) {
                  var elStyle = this[i].style;
                  elStyle.webkitTransform = elStyle.MsTransform = elStyle.msTransform = elStyle.MozTransform = elStyle.OTransform = elStyle.transform = transform;
              }
              return this;
          };
      }
      if (!('transition' in domLib.fn)) {
          domLib.fn.transition = function (duration) {
              if (typeof duration !== 'string') {
                  duration = duration + 'ms';
              }
              for (var i = 0; i < this.length; i++) {
                  var elStyle = this[i].style;
                  elStyle.webkitTransitionDuration = elStyle.MsTransitionDuration = elStyle.msTransitionDuration = elStyle.MozTransitionDuration = elStyle.OTransitionDuration = elStyle.transitionDuration = duration;
              }
              return this;
          };
      }
      if (!('outerWidth' in domLib.fn)) {
          domLib.fn.outerWidth = function (includeMargins) {
              if (this.length > 0) {
                  if (includeMargins)
                      return this[0].offsetWidth + parseFloat(this.css('margin-right')) + parseFloat(this.css('margin-left'));
                  else
                      return this[0].offsetWidth;
              }
              else return null;
          };
      }
  }


  window.Swiper = Swiper;
})();

/*===========================
Swiper AMD Export
===========================*/
if (typeof(module) !== 'undefined')
{
  module.exports = window.Swiper;
}
else if (typeof define === 'function' && define.amd) {
  define([], function () {
      'use strict';
      return window.Swiper;
  });
}

//# sourceMappingURL=maps/swiper.jquery.js.map

/*!
 * jQuery Cookiebar Plugin
 * https://github.com/carlwoodhouse/jquery.cookieBar
 *
 * Copyright 2012-17, Carl Woodhouse. the cookie function is inspired by https://github.com/carhartl/jquery-cookie
 * Disclaimer: if you still get fined for not complying with the eu cookielaw, it's not our fault.
 * Licence: MIT
 */

(function ($) {
	$.cookie = function (key, value, options) {
		if (arguments.length > 1 && (!/Object/.test(Object.prototype.toString.call(value)) || value === null || value === undefined)) {
			options = $.extend({}, options);

			if (value === null || value === undefined) {
				options.expires = -1;
			}

			if (typeof options.expires === 'number') {
				var days = options.expires, t = options.expires = new Date();
				t.setDate(t.getDate() + days);
			}

			value = String(value);

			return (document.cookie = [
				encodeURIComponent(key), '=', options.raw ? value : encodeURIComponent(value),
				options.expires ? '; expires=' + options.expires.toUTCString() : '', // max-age is not supported by IE
				options.path ? '; path=' + options.path : '',
				options.domain ? '; domain=' + options.domain : '',
				options.secure ? '; secure' : ''
			].join(''));
		}
		options = value || {};
		var decode = options.raw ? function (s) { return s; } : decodeURIComponent;

		var pairs = document.cookie.split('; ');
		for (var i = 0, pair; pair = pairs[i] && pairs[i].split('='); i++) {
			// IE
			if (decode(pair[0]) === key) return decode(pair[1] || '');
		}
		return null;
	};

	$.fn.cookieBar = function (options) {
		var settings = $.extend({
			'closeButton': 'none',
			'hideOnClose': true,
			'secure': false,
			'path': '/',
			'domain': ''
		}, options);

		return this.each(function () {
			var cookiebar = $(this);

			// just in case they didnt hide it by default.
			cookiebar.hide();

			// if close button not defined. define it!
			if (settings.closeButton == 'none') {
				cookiebar.append('<a class="cookiebar-close">Continue</a>');
				$.extend(settings, { 'closeButton': '.cookiebar-close' });
			}

			if ($.cookie('cookiebar') != 'hide') {
				cookiebar.show();
			}

			cookiebar.find(settings.closeButton).click(function () {
				if (settings.hideOnClose) {
					cookiebar.hide();
				}
				$.cookie('cookiebar', 'hide', { path: settings.path, secure: settings.secure, domain: settings.domain, expires: 30 });
				cookiebar.trigger('cookieBar-close');
				return false;
			});
		});
	};

	// self injection init
	$.cookieBar = function (options) {
		$('body').prepend('<div class="ui-widget"><div style="display: none;" class="cookie-message ui-widget-header blue"><p>By using this website you allow us to place cookies on your computer. They are harmless and never personally identify you.</p></div></div>');
		$('.cookie-message').cookieBar(options);
	};
})(jQuery);
/*!
 * jQuery Form Plugin
 * version: 3.51.0-2014.06.20
 * Requires jQuery v1.5 or later
 * Copyright (c) 2014 M. Alsup
 * Examples and documentation at: http://malsup.com/jquery/form/
 * Project repository: https://github.com/malsup/form
 * Dual licensed under the MIT and GPL licenses.
 * https://github.com/malsup/form#copyright-and-license
 */
!function(e){"use strict";"function"==typeof define&&define.amd?define(["jquery"],e):e("undefined"!=typeof jQuery?jQuery:window.Zepto)}(function(e){"use strict";function t(t){var r=t.data;t.isDefaultPrevented()||(t.preventDefault(),e(t.target).ajaxSubmit(r))}function r(t){var r=t.target,a=e(r);if(!a.is("[type=submit],[type=image]")){var n=a.closest("[type=submit]");if(0===n.length)return;r=n[0]}var i=this;if(i.clk=r,"image"==r.type)if(void 0!==t.offsetX)i.clk_x=t.offsetX,i.clk_y=t.offsetY;else if("function"==typeof e.fn.offset){var o=a.offset();i.clk_x=t.pageX-o.left,i.clk_y=t.pageY-o.top}else i.clk_x=t.pageX-r.offsetLeft,i.clk_y=t.pageY-r.offsetTop;setTimeout(function(){i.clk=i.clk_x=i.clk_y=null},100)}function a(){if(e.fn.ajaxSubmit.debug){var t="[jquery.form] "+Array.prototype.join.call(arguments,"");window.console&&window.console.log?window.console.log(t):window.opera&&window.opera.postError&&window.opera.postError(t)}}var n={};n.fileapi=void 0!==e("<input type='file'/>").get(0).files,n.formdata=void 0!==window.FormData;var i=!!e.fn.prop;e.fn.attr2=function(){if(!i)return this.attr.apply(this,arguments);var e=this.prop.apply(this,arguments);return e&&e.jquery||"string"==typeof e?e:this.attr.apply(this,arguments)},e.fn.ajaxSubmit=function(t){function r(r){var a,n,i=e.param(r,t.traditional).split("&"),o=i.length,s=[];for(a=0;o>a;a++)i[a]=i[a].replace(/\+/g," "),n=i[a].split("="),s.push([decodeURIComponent(n[0]),decodeURIComponent(n[1])]);return s}function o(a){for(var n=new FormData,i=0;i<a.length;i++)n.append(a[i].name,a[i].value);if(t.extraData){var o=r(t.extraData);for(i=0;i<o.length;i++)o[i]&&n.append(o[i][0],o[i][1])}t.data=null;var s=e.extend(!0,{},e.ajaxSettings,t,{contentType:!1,processData:!1,cache:!1,type:u||"POST"});t.uploadProgress&&(s.xhr=function(){var r=e.ajaxSettings.xhr();return r.upload&&r.upload.addEventListener("progress",function(e){var r=0,a=e.loaded||e.position,n=e.total;e.lengthComputable&&(r=Math.ceil(a/n*100)),t.uploadProgress(e,a,n,r)},!1),r}),s.data=null;var c=s.beforeSend;return s.beforeSend=function(e,r){r.data=t.formData?t.formData:n,c&&c.call(this,e,r)},e.ajax(s)}function s(r){function n(e){var t=null;try{e.contentWindow&&(t=e.contentWindow.document)}catch(r){a("cannot get iframe.contentWindow document: "+r)}if(t)return t;try{t=e.contentDocument?e.contentDocument:e.document}catch(r){a("cannot get iframe.contentDocument: "+r),t=e.document}return t}function o(){function t(){try{var e=n(g).readyState;a("state = "+e),e&&"uninitialized"==e.toLowerCase()&&setTimeout(t,50)}catch(r){a("Server abort: ",r," (",r.name,")"),s(k),j&&clearTimeout(j),j=void 0}}var r=f.attr2("target"),i=f.attr2("action"),o="multipart/form-data",c=f.attr("enctype")||f.attr("encoding")||o;w.setAttribute("target",p),(!u||/post/i.test(u))&&w.setAttribute("method","POST"),i!=m.url&&w.setAttribute("action",m.url),m.skipEncodingOverride||u&&!/post/i.test(u)||f.attr({encoding:"multipart/form-data",enctype:"multipart/form-data"}),m.timeout&&(j=setTimeout(function(){T=!0,s(D)},m.timeout));var l=[];try{if(m.extraData)for(var d in m.extraData)m.extraData.hasOwnProperty(d)&&l.push(e.isPlainObject(m.extraData[d])&&m.extraData[d].hasOwnProperty("name")&&m.extraData[d].hasOwnProperty("value")?e('<input type="hidden" name="'+m.extraData[d].name+'">').val(m.extraData[d].value).appendTo(w)[0]:e('<input type="hidden" name="'+d+'">').val(m.extraData[d]).appendTo(w)[0]);m.iframeTarget||v.appendTo("body"),g.attachEvent?g.attachEvent("onload",s):g.addEventListener("load",s,!1),setTimeout(t,15);try{w.submit()}catch(h){var x=document.createElement("form").submit;x.apply(w)}}finally{w.setAttribute("action",i),w.setAttribute("enctype",c),r?w.setAttribute("target",r):f.removeAttr("target"),e(l).remove()}}function s(t){if(!x.aborted&&!F){if(M=n(g),M||(a("cannot access response document"),t=k),t===D&&x)return x.abort("timeout"),void S.reject(x,"timeout");if(t==k&&x)return x.abort("server abort"),void S.reject(x,"error","server abort");if(M&&M.location.href!=m.iframeSrc||T){g.detachEvent?g.detachEvent("onload",s):g.removeEventListener("load",s,!1);var r,i="success";try{if(T)throw"timeout";var o="xml"==m.dataType||M.XMLDocument||e.isXMLDoc(M);if(a("isXml="+o),!o&&window.opera&&(null===M.body||!M.body.innerHTML)&&--O)return a("requeing onLoad callback, DOM not available"),void setTimeout(s,250);var u=M.body?M.body:M.documentElement;x.responseText=u?u.innerHTML:null,x.responseXML=M.XMLDocument?M.XMLDocument:M,o&&(m.dataType="xml"),x.getResponseHeader=function(e){var t={"content-type":m.dataType};return t[e.toLowerCase()]},u&&(x.status=Number(u.getAttribute("status"))||x.status,x.statusText=u.getAttribute("statusText")||x.statusText);var c=(m.dataType||"").toLowerCase(),l=/(json|script|text)/.test(c);if(l||m.textarea){var f=M.getElementsByTagName("textarea")[0];if(f)x.responseText=f.value,x.status=Number(f.getAttribute("status"))||x.status,x.statusText=f.getAttribute("statusText")||x.statusText;else if(l){var p=M.getElementsByTagName("pre")[0],h=M.getElementsByTagName("body")[0];p?x.responseText=p.textContent?p.textContent:p.innerText:h&&(x.responseText=h.textContent?h.textContent:h.innerText)}}else"xml"==c&&!x.responseXML&&x.responseText&&(x.responseXML=X(x.responseText));try{E=_(x,c,m)}catch(y){i="parsererror",x.error=r=y||i}}catch(y){a("error caught: ",y),i="error",x.error=r=y||i}x.aborted&&(a("upload aborted"),i=null),x.status&&(i=x.status>=200&&x.status<300||304===x.status?"success":"error"),"success"===i?(m.success&&m.success.call(m.context,E,"success",x),S.resolve(x.responseText,"success",x),d&&e.event.trigger("ajaxSuccess",[x,m])):i&&(void 0===r&&(r=x.statusText),m.error&&m.error.call(m.context,x,i,r),S.reject(x,"error",r),d&&e.event.trigger("ajaxError",[x,m,r])),d&&e.event.trigger("ajaxComplete",[x,m]),d&&!--e.active&&e.event.trigger("ajaxStop"),m.complete&&m.complete.call(m.context,x,i),F=!0,m.timeout&&clearTimeout(j),setTimeout(function(){m.iframeTarget?v.attr("src",m.iframeSrc):v.remove(),x.responseXML=null},100)}}}var c,l,m,d,p,v,g,x,y,b,T,j,w=f[0],S=e.Deferred();if(S.abort=function(e){x.abort(e)},r)for(l=0;l<h.length;l++)c=e(h[l]),i?c.prop("disabled",!1):c.removeAttr("disabled");if(m=e.extend(!0,{},e.ajaxSettings,t),m.context=m.context||m,p="jqFormIO"+(new Date).getTime(),m.iframeTarget?(v=e(m.iframeTarget),b=v.attr2("name"),b?p=b:v.attr2("name",p)):(v=e('<iframe name="'+p+'" src="'+m.iframeSrc+'" />'),v.css({position:"absolute",top:"-1000px",left:"-1000px"})),g=v[0],x={aborted:0,responseText:null,responseXML:null,status:0,statusText:"n/a",getAllResponseHeaders:function(){},getResponseHeader:function(){},setRequestHeader:function(){},abort:function(t){var r="timeout"===t?"timeout":"aborted";a("aborting upload... "+r),this.aborted=1;try{g.contentWindow.document.execCommand&&g.contentWindow.document.execCommand("Stop")}catch(n){}v.attr("src",m.iframeSrc),x.error=r,m.error&&m.error.call(m.context,x,r,t),d&&e.event.trigger("ajaxError",[x,m,r]),m.complete&&m.complete.call(m.context,x,r)}},d=m.global,d&&0===e.active++&&e.event.trigger("ajaxStart"),d&&e.event.trigger("ajaxSend",[x,m]),m.beforeSend&&m.beforeSend.call(m.context,x,m)===!1)return m.global&&e.active--,S.reject(),S;if(x.aborted)return S.reject(),S;y=w.clk,y&&(b=y.name,b&&!y.disabled&&(m.extraData=m.extraData||{},m.extraData[b]=y.value,"image"==y.type&&(m.extraData[b+".x"]=w.clk_x,m.extraData[b+".y"]=w.clk_y)));var D=1,k=2,A=e("meta[name=csrf-token]").attr("content"),L=e("meta[name=csrf-param]").attr("content");L&&A&&(m.extraData=m.extraData||{},m.extraData[L]=A),m.forceSync?o():setTimeout(o,10);var E,M,F,O=50,X=e.parseXML||function(e,t){return window.ActiveXObject?(t=new ActiveXObject("Microsoft.XMLDOM"),t.async="false",t.loadXML(e)):t=(new DOMParser).parseFromString(e,"text/xml"),t&&t.documentElement&&"parsererror"!=t.documentElement.nodeName?t:null},C=e.parseJSON||function(e){return window.eval("("+e+")")},_=function(t,r,a){var n=t.getResponseHeader("content-type")||"",i="xml"===r||!r&&n.indexOf("xml")>=0,o=i?t.responseXML:t.responseText;return i&&"parsererror"===o.documentElement.nodeName&&e.error&&e.error("parsererror"),a&&a.dataFilter&&(o=a.dataFilter(o,r)),"string"==typeof o&&("json"===r||!r&&n.indexOf("json")>=0?o=C(o):("script"===r||!r&&n.indexOf("javascript")>=0)&&e.globalEval(o)),o};return S}if(!this.length)return a("ajaxSubmit: skipping submit process - no element selected"),this;var u,c,l,f=this;"function"==typeof t?t={success:t}:void 0===t&&(t={}),u=t.type||this.attr2("method"),c=t.url||this.attr2("action"),l="string"==typeof c?e.trim(c):"",l=l||window.location.href||"",l&&(l=(l.match(/^([^#]+)/)||[])[1]),t=e.extend(!0,{url:l,success:e.ajaxSettings.success,type:u||e.ajaxSettings.type,iframeSrc:/^https/i.test(window.location.href||"")?"javascript:false":"about:blank"},t);var m={};if(this.trigger("form-pre-serialize",[this,t,m]),m.veto)return a("ajaxSubmit: submit vetoed via form-pre-serialize trigger"),this;if(t.beforeSerialize&&t.beforeSerialize(this,t)===!1)return a("ajaxSubmit: submit aborted via beforeSerialize callback"),this;var d=t.traditional;void 0===d&&(d=e.ajaxSettings.traditional);var p,h=[],v=this.formToArray(t.semantic,h);if(t.data&&(t.extraData=t.data,p=e.param(t.data,d)),t.beforeSubmit&&t.beforeSubmit(v,this,t)===!1)return a("ajaxSubmit: submit aborted via beforeSubmit callback"),this;if(this.trigger("form-submit-validate",[v,this,t,m]),m.veto)return a("ajaxSubmit: submit vetoed via form-submit-validate trigger"),this;var g=e.param(v,d);p&&(g=g?g+"&"+p:p),"GET"==t.type.toUpperCase()?(t.url+=(t.url.indexOf("?")>=0?"&":"?")+g,t.data=null):t.data=g;var x=[];if(t.resetForm&&x.push(function(){f.resetForm()}),t.clearForm&&x.push(function(){f.clearForm(t.includeHidden)}),!t.dataType&&t.target){var y=t.success||function(){};x.push(function(r){var a=t.replaceTarget?"replaceWith":"html";e(t.target)[a](r).each(y,arguments)})}else t.success&&x.push(t.success);if(t.success=function(e,r,a){for(var n=t.context||this,i=0,o=x.length;o>i;i++)x[i].apply(n,[e,r,a||f,f])},t.error){var b=t.error;t.error=function(e,r,a){var n=t.context||this;b.apply(n,[e,r,a,f])}}if(t.complete){var T=t.complete;t.complete=function(e,r){var a=t.context||this;T.apply(a,[e,r,f])}}var j=e("input[type=file]:enabled",this).filter(function(){return""!==e(this).val()}),w=j.length>0,S="multipart/form-data",D=f.attr("enctype")==S||f.attr("encoding")==S,k=n.fileapi&&n.formdata;a("fileAPI :"+k);var A,L=(w||D)&&!k;t.iframe!==!1&&(t.iframe||L)?t.closeKeepAlive?e.get(t.closeKeepAlive,function(){A=s(v)}):A=s(v):A=(w||D)&&k?o(v):e.ajax(t),f.removeData("jqxhr").data("jqxhr",A);for(var E=0;E<h.length;E++)h[E]=null;return this.trigger("form-submit-notify",[this,t]),this},e.fn.ajaxForm=function(n){if(n=n||{},n.delegation=n.delegation&&e.isFunction(e.fn.on),!n.delegation&&0===this.length){var i={s:this.selector,c:this.context};return!e.isReady&&i.s?(a("DOM not ready, queuing ajaxForm"),e(function(){e(i.s,i.c).ajaxForm(n)}),this):(a("terminating; zero elements found by selector"+(e.isReady?"":" (DOM not ready)")),this)}return n.delegation?(e(document).off("submit.form-plugin",this.selector,t).off("click.form-plugin",this.selector,r).on("submit.form-plugin",this.selector,n,t).on("click.form-plugin",this.selector,n,r),this):this.ajaxFormUnbind().bind("submit.form-plugin",n,t).bind("click.form-plugin",n,r)},e.fn.ajaxFormUnbind=function(){return this.unbind("submit.form-plugin click.form-plugin")},e.fn.formToArray=function(t,r){var a=[];if(0===this.length)return a;var i,o=this[0],s=this.attr("id"),u=t?o.getElementsByTagName("*"):o.elements;if(u&&!/MSIE [678]/.test(navigator.userAgent)&&(u=e(u).get()),s&&(i=e(':input[form="'+s+'"]').get(),i.length&&(u=(u||[]).concat(i))),!u||!u.length)return a;var c,l,f,m,d,p,h;for(c=0,p=u.length;p>c;c++)if(d=u[c],f=d.name,f&&!d.disabled)if(t&&o.clk&&"image"==d.type)o.clk==d&&(a.push({name:f,value:e(d).val(),type:d.type}),a.push({name:f+".x",value:o.clk_x},{name:f+".y",value:o.clk_y}));else if(m=e.fieldValue(d,!0),m&&m.constructor==Array)for(r&&r.push(d),l=0,h=m.length;h>l;l++)a.push({name:f,value:m[l]});else if(n.fileapi&&"file"==d.type){r&&r.push(d);var v=d.files;if(v.length)for(l=0;l<v.length;l++)a.push({name:f,value:v[l],type:d.type});else a.push({name:f,value:"",type:d.type})}else null!==m&&"undefined"!=typeof m&&(r&&r.push(d),a.push({name:f,value:m,type:d.type,required:d.required}));if(!t&&o.clk){var g=e(o.clk),x=g[0];f=x.name,f&&!x.disabled&&"image"==x.type&&(a.push({name:f,value:g.val()}),a.push({name:f+".x",value:o.clk_x},{name:f+".y",value:o.clk_y}))}return a},e.fn.formSerialize=function(t){return e.param(this.formToArray(t))},e.fn.fieldSerialize=function(t){var r=[];return this.each(function(){var a=this.name;if(a){var n=e.fieldValue(this,t);if(n&&n.constructor==Array)for(var i=0,o=n.length;o>i;i++)r.push({name:a,value:n[i]});else null!==n&&"undefined"!=typeof n&&r.push({name:this.name,value:n})}}),e.param(r)},e.fn.fieldValue=function(t){for(var r=[],a=0,n=this.length;n>a;a++){var i=this[a],o=e.fieldValue(i,t);null===o||"undefined"==typeof o||o.constructor==Array&&!o.length||(o.constructor==Array?e.merge(r,o):r.push(o))}return r},e.fieldValue=function(t,r){var a=t.name,n=t.type,i=t.tagName.toLowerCase();if(void 0===r&&(r=!0),r&&(!a||t.disabled||"reset"==n||"button"==n||("checkbox"==n||"radio"==n)&&!t.checked||("submit"==n||"image"==n)&&t.form&&t.form.clk!=t||"select"==i&&-1==t.selectedIndex))return null;if("select"==i){var o=t.selectedIndex;if(0>o)return null;for(var s=[],u=t.options,c="select-one"==n,l=c?o+1:u.length,f=c?o:0;l>f;f++){var m=u[f];if(m.selected){var d=m.value;if(d||(d=m.attributes&&m.attributes.value&&!m.attributes.value.specified?m.text:m.value),c)return d;s.push(d)}}return s}return e(t).val()},e.fn.clearForm=function(t){return this.each(function(){e("input,select,textarea",this).clearFields(t)})},e.fn.clearFields=e.fn.clearInputs=function(t){var r=/^(?:color|date|datetime|email|month|number|password|range|search|tel|text|time|url|week)$/i;return this.each(function(){var a=this.type,n=this.tagName.toLowerCase();r.test(a)||"textarea"==n?this.value="":"checkbox"==a||"radio"==a?this.checked=!1:"select"==n?this.selectedIndex=-1:"file"==a?/MSIE/.test(navigator.userAgent)?e(this).replaceWith(e(this).clone(!0)):e(this).val(""):t&&(t===!0&&/hidden/.test(a)||"string"==typeof t&&e(this).is(t))&&(this.value="")})},e.fn.resetForm=function(){return this.each(function(){("function"==typeof this.reset||"object"==typeof this.reset&&!this.reset.nodeType)&&this.reset()})},e.fn.enable=function(e){return void 0===e&&(e=!0),this.each(function(){this.disabled=!e})},e.fn.selected=function(t){return void 0===t&&(t=!0),this.each(function(){var r=this.type;if("checkbox"==r||"radio"==r)this.checked=t;else if("option"==this.tagName.toLowerCase()){var a=e(this).parent("select");t&&a[0]&&"select-one"==a[0].type&&a.find("option").selected(!1),this.selected=t}})},e.fn.ajaxSubmit.debug=!1});
/*!
 * jQuery Plugin: Are-You-Sure (Dirty Form Detection)
 * https://github.com/codedance/jquery.AreYouSure/
 *
 * Copyright (c) 2012-2014, Chris Dance and PaperCut Software http://www.papercut.com/
 * Dual licensed under the MIT or GPL Version 2 licenses.
 * http://jquery.org/license
 *
 * Author:  chris.dance@papercut.com
 * Version: 1.9.0
 * Date:    13th August 2014
 */
(function($) {
  
  $.fn.areYouSure = function(options) {
      
    var settings = $.extend(
      {
        'message' : 'You have unsaved changes!',
        'dirtyClass' : 'dirty',
        'change' : null,
        'silent' : false,
        'addRemoveFieldsMarksDirty' : false,
        'fieldEvents' : 'change keyup propertychange input',
        'fieldSelector': ":input:not(input[type=submit]):not(input[type=button])"
      }, options);

    var getValue = function($field) {
      if ($field.hasClass('ays-ignore')
          || $field.hasClass('aysIgnore')
          || $field.attr('data-ays-ignore')
          || $field.attr('name') === undefined) {
        return null;
      }

      if ($field.is(':disabled')) {
        return 'ays-disabled';
      }

      var val;
      var type = $field.attr('type');
      if ($field.is('select')) {
        type = 'select';
      }

      switch (type) {
        case 'checkbox':
        case 'radio':
          val = $field.is(':checked');
          break;
        case 'select':
          val = '';
          $field.find('option').each(function(o) {
            var $option = $(this);
            if ($option.is(':selected')) {
              val += $option.val();
            }
          });
          break;
        default:
          val = $field.val();
      }

      return val;
    };

    var storeOrigValue = function($field) {
      $field.data('ays-orig', getValue($field));
    };

    var checkForm = function(evt) {

      var isFieldDirty = function($field) {
        var origValue = $field.data('ays-orig');
        if (undefined === origValue) {
          return false;
        }
        return (getValue($field) != origValue);
      };

      var $form = ($(this).is('form')) 
                    ? $(this)
                    : $(this).parents('form');

      // Test on the target first as it's the most likely to be dirty
      if (isFieldDirty($(evt.target))) {
        setDirtyStatus($form, true);
        return;
      }

      $fields = $form.find(settings.fieldSelector);

      if (settings.addRemoveFieldsMarksDirty) {              
        // Check if field count has changed
        var origCount = $form.data("ays-orig-field-count");
        if (origCount != $fields.length) {
          setDirtyStatus($form, true);
          return;
        }
      }

      // Brute force - check each field
      var isDirty = false;
      $fields.each(function() {
        $field = $(this);
        if (isFieldDirty($field)) {
          isDirty = true;
          return false; // break
        }
      });
      
      setDirtyStatus($form, isDirty);
    };

    var initForm = function($form) {
      var fields = $form.find(settings.fieldSelector);
      $(fields).each(function() { storeOrigValue($(this)); });
      $(fields).unbind(settings.fieldEvents, checkForm);
      $(fields).bind(settings.fieldEvents, checkForm);
      $form.data("ays-orig-field-count", $(fields).length);
      setDirtyStatus($form, false);
    };

    var setDirtyStatus = function($form, isDirty) {
      var changed = isDirty != $form.hasClass(settings.dirtyClass);
      $form.toggleClass(settings.dirtyClass, isDirty);
        
      // Fire change event if required
      if (changed) {
        if (settings.change) settings.change.call($form, $form);

        if (isDirty) $form.trigger('dirty.areYouSure', [$form]);
        if (!isDirty) $form.trigger('clean.areYouSure', [$form]);
        $form.trigger('change.areYouSure', [$form]);
      }
    };

    var rescan = function() {
      var $form = $(this);
      var fields = $form.find(settings.fieldSelector);
      $(fields).each(function() {
        var $field = $(this);
        if (!$field.data('ays-orig')) {
          storeOrigValue($field);
          $field.bind(settings.fieldEvents, checkForm);
        }
      });
      // Check for changes while we're here
      $form.trigger('checkform.areYouSure');
    };

    var reinitialize = function() {
      initForm($(this));
    }

    if (!settings.silent && !window.aysUnloadSet) {
      window.aysUnloadSet = true;
      $(window).bind('beforeunload', function() {
        $dirtyForms = $("form").filter('.' + settings.dirtyClass);
        if ($dirtyForms.length == 0) {
          return;
        }
        // Prevent multiple prompts - seen on Chrome and IE
        if (navigator.userAgent.toLowerCase().match(/msie|chrome/)) {
          if (window.aysHasPrompted) {
            return;
          }
          window.aysHasPrompted = true;
          window.setTimeout(function() {window.aysHasPrompted = false;}, 900);
        }
        return settings.message;
      });
    }

    return this.each(function(elem) {
      if (!$(this).is('form')) {
        return;
      }
      var $form = $(this);
        
      $form.submit(function() {
        $form.removeClass(settings.dirtyClass);
      });
      $form.bind('reset', function() { setDirtyStatus($form, false); });
      // Add a custom events
      $form.bind('rescan.areYouSure', rescan);
      $form.bind('reinitialize.areYouSure', reinitialize);
      $form.bind('checkform.areYouSure', checkForm);
      initForm($form);
    });
  };
})(jQuery);
/*!
 * Select2 4.0.4
 * https://select2.github.io
 *
 * Released under the MIT license
 * https://github.com/select2/select2/blob/master/LICENSE.md
 */
(function (factory) {
  if (typeof define === 'function' && define.amd) {
    // AMD. Register as an anonymous module.
    define(['jquery'], factory);
  } else if (typeof module === 'object' && module.exports) {
    // Node/CommonJS
    module.exports = function (root, jQuery) {
      if (jQuery === undefined) {
        // require('jQuery') returns a factory that requires window to
        // build a jQuery instance, we normalize how we use modules
        // that require this pattern but the window provided is a noop
        // if it's defined (how jquery works)
        if (typeof window !== 'undefined') {
          jQuery = require('jquery');
        }
        else {
          jQuery = require('jquery')(root);
        }
      }
      factory(jQuery);
      return jQuery;
    };
  } else {
    // Browser globals
    factory(jQuery);
  }
} (function (jQuery) {
  // This is needed so we can catch the AMD loader configuration and use it
  // The inner file should be wrapped (by `banner.start.js`) in a function that
  // returns the AMD loader references.
  var S2 =(function () {
  // Restore the Select2 AMD loader so it can be used
  // Needed mostly in the language files, where the loader is not inserted
  if (jQuery && jQuery.fn && jQuery.fn.select2 && jQuery.fn.select2.amd) {
    var S2 = jQuery.fn.select2.amd;
  }
var S2;(function () { if (!S2 || !S2.requirejs) {
if (!S2) { S2 = {}; } else { require = S2; }
/**
 * @license almond 0.3.3 Copyright jQuery Foundation and other contributors.
 * Released under MIT license, http://github.com/requirejs/almond/LICENSE
 */
//Going sloppy to avoid 'use strict' string cost, but strict practices should
//be followed.
/*global setTimeout: false */

var requirejs, require, define;
(function (undef) {
    var main, req, makeMap, handlers,
        defined = {},
        waiting = {},
        config = {},
        defining = {},
        hasOwn = Object.prototype.hasOwnProperty,
        aps = [].slice,
        jsSuffixRegExp = /\.js$/;

    function hasProp(obj, prop) {
        return hasOwn.call(obj, prop);
    }

    /**
     * Given a relative module name, like ./something, normalize it to
     * a real name that can be mapped to a path.
     * @param {String} name the relative name
     * @param {String} baseName a real name that the name arg is relative
     * to.
     * @returns {String} normalized name
     */
    function normalize(name, baseName) {
        var nameParts, nameSegment, mapValue, foundMap, lastIndex,
            foundI, foundStarMap, starI, i, j, part, normalizedBaseParts,
            baseParts = baseName && baseName.split("/"),
            map = config.map,
            starMap = (map && map['*']) || {};

        //Adjust any relative paths.
        if (name) {
            name = name.split('/');
            lastIndex = name.length - 1;

            // If wanting node ID compatibility, strip .js from end
            // of IDs. Have to do this here, and not in nameToUrl
            // because node allows either .js or non .js to map
            // to same file.
            if (config.nodeIdCompat && jsSuffixRegExp.test(name[lastIndex])) {
                name[lastIndex] = name[lastIndex].replace(jsSuffixRegExp, '');
            }

            // Starts with a '.' so need the baseName
            if (name[0].charAt(0) === '.' && baseParts) {
                //Convert baseName to array, and lop off the last part,
                //so that . matches that 'directory' and not name of the baseName's
                //module. For instance, baseName of 'one/two/three', maps to
                //'one/two/three.js', but we want the directory, 'one/two' for
                //this normalization.
                normalizedBaseParts = baseParts.slice(0, baseParts.length - 1);
                name = normalizedBaseParts.concat(name);
            }

            //start trimDots
            for (i = 0; i < name.length; i++) {
                part = name[i];
                if (part === '.') {
                    name.splice(i, 1);
                    i -= 1;
                } else if (part === '..') {
                    // If at the start, or previous value is still ..,
                    // keep them so that when converted to a path it may
                    // still work when converted to a path, even though
                    // as an ID it is less than ideal. In larger point
                    // releases, may be better to just kick out an error.
                    if (i === 0 || (i === 1 && name[2] === '..') || name[i - 1] === '..') {
                        continue;
                    } else if (i > 0) {
                        name.splice(i - 1, 2);
                        i -= 2;
                    }
                }
            }
            //end trimDots

            name = name.join('/');
        }

        //Apply map config if available.
        if ((baseParts || starMap) && map) {
            nameParts = name.split('/');

            for (i = nameParts.length; i > 0; i -= 1) {
                nameSegment = nameParts.slice(0, i).join("/");

                if (baseParts) {
                    //Find the longest baseName segment match in the config.
                    //So, do joins on the biggest to smallest lengths of baseParts.
                    for (j = baseParts.length; j > 0; j -= 1) {
                        mapValue = map[baseParts.slice(0, j).join('/')];

                        //baseName segment has  config, find if it has one for
                        //this name.
                        if (mapValue) {
                            mapValue = mapValue[nameSegment];
                            if (mapValue) {
                                //Match, update name to the new value.
                                foundMap = mapValue;
                                foundI = i;
                                break;
                            }
                        }
                    }
                }

                if (foundMap) {
                    break;
                }

                //Check for a star map match, but just hold on to it,
                //if there is a shorter segment match later in a matching
                //config, then favor over this star map.
                if (!foundStarMap && starMap && starMap[nameSegment]) {
                    foundStarMap = starMap[nameSegment];
                    starI = i;
                }
            }

            if (!foundMap && foundStarMap) {
                foundMap = foundStarMap;
                foundI = starI;
            }

            if (foundMap) {
                nameParts.splice(0, foundI, foundMap);
                name = nameParts.join('/');
            }
        }

        return name;
    }

    function makeRequire(relName, forceSync) {
        return function () {
            //A version of a require function that passes a moduleName
            //value for items that may need to
            //look up paths relative to the moduleName
            var args = aps.call(arguments, 0);

            //If first arg is not require('string'), and there is only
            //one arg, it is the array form without a callback. Insert
            //a null so that the following concat is correct.
            if (typeof args[0] !== 'string' && args.length === 1) {
                args.push(null);
            }
            return req.apply(undef, args.concat([relName, forceSync]));
        };
    }

    function makeNormalize(relName) {
        return function (name) {
            return normalize(name, relName);
        };
    }

    function makeLoad(depName) {
        return function (value) {
            defined[depName] = value;
        };
    }

    function callDep(name) {
        if (hasProp(waiting, name)) {
            var args = waiting[name];
            delete waiting[name];
            defining[name] = true;
            main.apply(undef, args);
        }

        if (!hasProp(defined, name) && !hasProp(defining, name)) {
            throw new Error('No ' + name);
        }
        return defined[name];
    }

    //Turns a plugin!resource to [plugin, resource]
    //with the plugin being undefined if the name
    //did not have a plugin prefix.
    function splitPrefix(name) {
        var prefix,
            index = name ? name.indexOf('!') : -1;
        if (index > -1) {
            prefix = name.substring(0, index);
            name = name.substring(index + 1, name.length);
        }
        return [prefix, name];
    }

    //Creates a parts array for a relName where first part is plugin ID,
    //second part is resource ID. Assumes relName has already been normalized.
    function makeRelParts(relName) {
        return relName ? splitPrefix(relName) : [];
    }

    /**
     * Makes a name map, normalizing the name, and using a plugin
     * for normalization if necessary. Grabs a ref to plugin
     * too, as an optimization.
     */
    makeMap = function (name, relParts) {
        var plugin,
            parts = splitPrefix(name),
            prefix = parts[0],
            relResourceName = relParts[1];

        name = parts[1];

        if (prefix) {
            prefix = normalize(prefix, relResourceName);
            plugin = callDep(prefix);
        }

        //Normalize according
        if (prefix) {
            if (plugin && plugin.normalize) {
                name = plugin.normalize(name, makeNormalize(relResourceName));
            } else {
                name = normalize(name, relResourceName);
            }
        } else {
            name = normalize(name, relResourceName);
            parts = splitPrefix(name);
            prefix = parts[0];
            name = parts[1];
            if (prefix) {
                plugin = callDep(prefix);
            }
        }

        //Using ridiculous property names for space reasons
        return {
            f: prefix ? prefix + '!' + name : name, //fullName
            n: name,
            pr: prefix,
            p: plugin
        };
    };

    function makeConfig(name) {
        return function () {
            return (config && config.config && config.config[name]) || {};
        };
    }

    handlers = {
        require: function (name) {
            return makeRequire(name);
        },
        exports: function (name) {
            var e = defined[name];
            if (typeof e !== 'undefined') {
                return e;
            } else {
                return (defined[name] = {});
            }
        },
        module: function (name) {
            return {
                id: name,
                uri: '',
                exports: defined[name],
                config: makeConfig(name)
            };
        }
    };

    main = function (name, deps, callback, relName) {
        var cjsModule, depName, ret, map, i, relParts,
            args = [],
            callbackType = typeof callback,
            usingExports;

        //Use name if no relName
        relName = relName || name;
        relParts = makeRelParts(relName);

        //Call the callback to define the module, if necessary.
        if (callbackType === 'undefined' || callbackType === 'function') {
            //Pull out the defined dependencies and pass the ordered
            //values to the callback.
            //Default to [require, exports, module] if no deps
            deps = !deps.length && callback.length ? ['require', 'exports', 'module'] : deps;
            for (i = 0; i < deps.length; i += 1) {
                map = makeMap(deps[i], relParts);
                depName = map.f;

                //Fast path CommonJS standard dependencies.
                if (depName === "require") {
                    args[i] = handlers.require(name);
                } else if (depName === "exports") {
                    //CommonJS module spec 1.1
                    args[i] = handlers.exports(name);
                    usingExports = true;
                } else if (depName === "module") {
                    //CommonJS module spec 1.1
                    cjsModule = args[i] = handlers.module(name);
                } else if (hasProp(defined, depName) ||
                           hasProp(waiting, depName) ||
                           hasProp(defining, depName)) {
                    args[i] = callDep(depName);
                } else if (map.p) {
                    map.p.load(map.n, makeRequire(relName, true), makeLoad(depName), {});
                    args[i] = defined[depName];
                } else {
                    throw new Error(name + ' missing ' + depName);
                }
            }

            ret = callback ? callback.apply(defined[name], args) : undefined;

            if (name) {
                //If setting exports via "module" is in play,
                //favor that over return value and exports. After that,
                //favor a non-undefined return value over exports use.
                if (cjsModule && cjsModule.exports !== undef &&
                        cjsModule.exports !== defined[name]) {
                    defined[name] = cjsModule.exports;
                } else if (ret !== undef || !usingExports) {
                    //Use the return value from the function.
                    defined[name] = ret;
                }
            }
        } else if (name) {
            //May just be an object definition for the module. Only
            //worry about defining if have a module name.
            defined[name] = callback;
        }
    };

    requirejs = require = req = function (deps, callback, relName, forceSync, alt) {
        if (typeof deps === "string") {
            if (handlers[deps]) {
                //callback in this case is really relName
                return handlers[deps](callback);
            }
            //Just return the module wanted. In this scenario, the
            //deps arg is the module name, and second arg (if passed)
            //is just the relName.
            //Normalize module name, if it contains . or ..
            return callDep(makeMap(deps, makeRelParts(callback)).f);
        } else if (!deps.splice) {
            //deps is a config object, not an array.
            config = deps;
            if (config.deps) {
                req(config.deps, config.callback);
            }
            if (!callback) {
                return;
            }

            if (callback.splice) {
                //callback is an array, which means it is a dependency list.
                //Adjust args if there are dependencies
                deps = callback;
                callback = relName;
                relName = null;
            } else {
                deps = undef;
            }
        }

        //Support require(['a'])
        callback = callback || function () {};

        //If relName is a function, it is an errback handler,
        //so remove it.
        if (typeof relName === 'function') {
            relName = forceSync;
            forceSync = alt;
        }

        //Simulate async callback;
        if (forceSync) {
            main(undef, deps, callback, relName);
        } else {
            //Using a non-zero value because of concern for what old browsers
            //do, and latest browsers "upgrade" to 4 if lower value is used:
            //http://www.whatwg.org/specs/web-apps/current-work/multipage/timers.html#dom-windowtimers-settimeout:
            //If want a value immediately, use require('id') instead -- something
            //that works in almond on the global level, but not guaranteed and
            //unlikely to work in other AMD implementations.
            setTimeout(function () {
                main(undef, deps, callback, relName);
            }, 4);
        }

        return req;
    };

    /**
     * Just drops the config on the floor, but returns req in case
     * the config return value is used.
     */
    req.config = function (cfg) {
        return req(cfg);
    };

    /**
     * Expose module registry for debugging and tooling
     */
    requirejs._defined = defined;

    define = function (name, deps, callback) {
        if (typeof name !== 'string') {
            throw new Error('See almond README: incorrect module build, no module name');
        }

        //This module may not have dependencies
        if (!deps.splice) {
            //deps is not an array, so probably means
            //an object literal or factory function for
            //the value. Adjust args.
            callback = deps;
            deps = [];
        }

        if (!hasProp(defined, name) && !hasProp(waiting, name)) {
            waiting[name] = [name, deps, callback];
        }
    };

    define.amd = {
        jQuery: true
    };
}());

S2.requirejs = requirejs;S2.require = require;S2.define = define;
}
}());
S2.define("almond", function(){});

/* global jQuery:false, $:false */
S2.define('jquery',[],function () {
  var _$ = jQuery || $;

  if (_$ == null && console && console.error) {
    console.error(
      'Select2: An instance of jQuery or a jQuery-compatible library was not ' +
      'found. Make sure that you are including jQuery before Select2 on your ' +
      'web page.'
    );
  }

  return _$;
});

S2.define('select2/utils',[
  'jquery'
], function ($) {
  var Utils = {};

  Utils.Extend = function (ChildClass, SuperClass) {
    var __hasProp = {}.hasOwnProperty;

    function BaseConstructor () {
      this.constructor = ChildClass;
    }

    for (var key in SuperClass) {
      if (__hasProp.call(SuperClass, key)) {
        ChildClass[key] = SuperClass[key];
      }
    }

    BaseConstructor.prototype = SuperClass.prototype;
    ChildClass.prototype = new BaseConstructor();
    ChildClass.__super__ = SuperClass.prototype;

    return ChildClass;
  };

  function getMethods (theClass) {
    var proto = theClass.prototype;

    var methods = [];

    for (var methodName in proto) {
      var m = proto[methodName];

      if (typeof m !== 'function') {
        continue;
      }

      if (methodName === 'constructor') {
        continue;
      }

      methods.push(methodName);
    }

    return methods;
  }

  Utils.Decorate = function (SuperClass, DecoratorClass) {
    var decoratedMethods = getMethods(DecoratorClass);
    var superMethods = getMethods(SuperClass);

    function DecoratedClass () {
      var unshift = Array.prototype.unshift;

      var argCount = DecoratorClass.prototype.constructor.length;

      var calledConstructor = SuperClass.prototype.constructor;

      if (argCount > 0) {
        unshift.call(arguments, SuperClass.prototype.constructor);

        calledConstructor = DecoratorClass.prototype.constructor;
      }

      calledConstructor.apply(this, arguments);
    }

    DecoratorClass.displayName = SuperClass.displayName;

    function ctr () {
      this.constructor = DecoratedClass;
    }

    DecoratedClass.prototype = new ctr();

    for (var m = 0; m < superMethods.length; m++) {
        var superMethod = superMethods[m];

        DecoratedClass.prototype[superMethod] =
          SuperClass.prototype[superMethod];
    }

    var calledMethod = function (methodName) {
      // Stub out the original method if it's not decorating an actual method
      var originalMethod = function () {};

      if (methodName in DecoratedClass.prototype) {
        originalMethod = DecoratedClass.prototype[methodName];
      }

      var decoratedMethod = DecoratorClass.prototype[methodName];

      return function () {
        var unshift = Array.prototype.unshift;

        unshift.call(arguments, originalMethod);

        return decoratedMethod.apply(this, arguments);
      };
    };

    for (var d = 0; d < decoratedMethods.length; d++) {
      var decoratedMethod = decoratedMethods[d];

      DecoratedClass.prototype[decoratedMethod] = calledMethod(decoratedMethod);
    }

    return DecoratedClass;
  };

  var Observable = function () {
    this.listeners = {};
  };

  Observable.prototype.on = function (event, callback) {
    this.listeners = this.listeners || {};

    if (event in this.listeners) {
      this.listeners[event].push(callback);
    } else {
      this.listeners[event] = [callback];
    }
  };

  Observable.prototype.trigger = function (event) {
    var slice = Array.prototype.slice;
    var params = slice.call(arguments, 1);

    this.listeners = this.listeners || {};

    // Params should always come in as an array
    if (params == null) {
      params = [];
    }

    // If there are no arguments to the event, use a temporary object
    if (params.length === 0) {
      params.push({});
    }

    // Set the `_type` of the first object to the event
    params[0]._type = event;

    if (event in this.listeners) {
      this.invoke(this.listeners[event], slice.call(arguments, 1));
    }

    if ('*' in this.listeners) {
      this.invoke(this.listeners['*'], arguments);
    }
  };

  Observable.prototype.invoke = function (listeners, params) {
    for (var i = 0, len = listeners.length; i < len; i++) {
      listeners[i].apply(this, params);
    }
  };

  Utils.Observable = Observable;

  Utils.generateChars = function (length) {
    var chars = '';

    for (var i = 0; i < length; i++) {
      var randomChar = Math.floor(Math.random() * 36);
      chars += randomChar.toString(36);
    }

    return chars;
  };

  Utils.bind = function (func, context) {
    return function () {
      func.apply(context, arguments);
    };
  };

  Utils._convertData = function (data) {
    for (var originalKey in data) {
      var keys = originalKey.split('-');

      var dataLevel = data;

      if (keys.length === 1) {
        continue;
      }

      for (var k = 0; k < keys.length; k++) {
        var key = keys[k];

        // Lowercase the first letter
        // By default, dash-separated becomes camelCase
        key = key.substring(0, 1).toLowerCase() + key.substring(1);

        if (!(key in dataLevel)) {
          dataLevel[key] = {};
        }

        if (k == keys.length - 1) {
          dataLevel[key] = data[originalKey];
        }

        dataLevel = dataLevel[key];
      }

      delete data[originalKey];
    }

    return data;
  };

  Utils.hasScroll = function (index, el) {
    // Adapted from the function created by @ShadowScripter
    // and adapted by @BillBarry on the Stack Exchange Code Review website.
    // The original code can be found at
    // http://codereview.stackexchange.com/q/13338
    // and was designed to be used with the Sizzle selector engine.

    var $el = $(el);
    var overflowX = el.style.overflowX;
    var overflowY = el.style.overflowY;

    //Check both x and y declarations
    if (overflowX === overflowY &&
        (overflowY === 'hidden' || overflowY === 'visible')) {
      return false;
    }

    if (overflowX === 'scroll' || overflowY === 'scroll') {
      return true;
    }

    return ($el.innerHeight() < el.scrollHeight ||
      $el.innerWidth() < el.scrollWidth);
  };

  Utils.escapeMarkup = function (markup) {
    var replaceMap = {
      '\\': '&#92;',
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      '\'': '&#39;',
      '/': '&#47;'
    };

    // Do not try to escape the markup if it's not a string
    if (typeof markup !== 'string') {
      return markup;
    }

    return String(markup).replace(/[&<>"'\/\\]/g, function (match) {
      return replaceMap[match];
    });
  };

  // Append an array of jQuery nodes to a given element.
  Utils.appendMany = function ($element, $nodes) {
    // jQuery 1.7.x does not support $.fn.append() with an array
    // Fall back to a jQuery object collection using $.fn.add()
    if ($.fn.jquery.substr(0, 3) === '1.7') {
      var $jqNodes = $();

      $.map($nodes, function (node) {
        $jqNodes = $jqNodes.add(node);
      });

      $nodes = $jqNodes;
    }

    $element.append($nodes);
  };

  return Utils;
});

S2.define('select2/results',[
  'jquery',
  './utils'
], function ($, Utils) {
  function Results ($element, options, dataAdapter) {
    this.$element = $element;
    this.data = dataAdapter;
    this.options = options;

    Results.__super__.constructor.call(this);
  }

  Utils.Extend(Results, Utils.Observable);

  Results.prototype.render = function () {
    var $results = $(
      '<ul class="select2-results__options" role="tree"></ul>'
    );

    if (this.options.get('multiple')) {
      $results.attr('aria-multiselectable', 'true');
    }

    this.$results = $results;

    return $results;
  };

  Results.prototype.clear = function () {
    this.$results.empty();
  };

  Results.prototype.displayMessage = function (params) {
    var escapeMarkup = this.options.get('escapeMarkup');

    this.clear();
    this.hideLoading();

    var $message = $(
      '<li role="treeitem" aria-live="assertive"' +
      ' class="select2-results__option"></li>'
    );

    var message = this.options.get('translations').get(params.message);

    $message.append(
      escapeMarkup(
        message(params.args)
      )
    );

    $message[0].className += ' select2-results__message';

    this.$results.append($message);
  };

  Results.prototype.hideMessages = function () {
    this.$results.find('.select2-results__message').remove();
  };

  Results.prototype.append = function (data) {
    this.hideLoading();

    var $options = [];

    if (data.results == null || data.results.length === 0) {
      if (this.$results.children().length === 0) {
        this.trigger('results:message', {
          message: 'noResults'
        });
      }

      return;
    }

    data.results = this.sort(data.results);

    for (var d = 0; d < data.results.length; d++) {
      var item = data.results[d];

      var $option = this.option(item);

      $options.push($option);
    }

    this.$results.append($options);
  };

  Results.prototype.position = function ($results, $dropdown) {
    var $resultsContainer = $dropdown.find('.select2-results');
    $resultsContainer.append($results);
  };

  Results.prototype.sort = function (data) {
    var sorter = this.options.get('sorter');

    return sorter(data);
  };

  Results.prototype.highlightFirstItem = function () {
    var $options = this.$results
      .find('.select2-results__option[aria-selected]');

    var $selected = $options.filter('[aria-selected=true]');

    // Check if there are any selected options
    if ($selected.length > 0) {
      // If there are selected options, highlight the first
      $selected.first().trigger('mouseenter');
    } else {
      // If there are no selected options, highlight the first option
      // in the dropdown
      $options.first().trigger('mouseenter');
    }

    this.ensureHighlightVisible();
  };

  Results.prototype.setClasses = function () {
    var self = this;

    this.data.current(function (selected) {
      var selectedIds = $.map(selected, function (s) {
        return s.id.toString();
      });

      var $options = self.$results
        .find('.select2-results__option[aria-selected]');

      $options.each(function () {
        var $option = $(this);

        var item = $.data(this, 'data');

        // id needs to be converted to a string when comparing
        var id = '' + item.id;

        if ((item.element != null && item.element.selected) ||
            (item.element == null && $.inArray(id, selectedIds) > -1)) {
          $option.attr('aria-selected', 'true');
        } else {
          $option.attr('aria-selected', 'false');
        }
      });

    });
  };

  Results.prototype.showLoading = function (params) {
    this.hideLoading();

    var loadingMore = this.options.get('translations').get('searching');

    var loading = {
      disabled: true,
      loading: true,
      text: loadingMore(params)
    };
    var $loading = this.option(loading);
    $loading.className += ' loading-results';

    this.$results.prepend($loading);
  };

  Results.prototype.hideLoading = function () {
    this.$results.find('.loading-results').remove();
  };

  Results.prototype.option = function (data) {
    var option = document.createElement('li');
    option.className = 'select2-results__option';

    var attrs = {
      'role': 'treeitem',
      'aria-selected': 'false'
    };

    if (data.disabled) {
      delete attrs['aria-selected'];
      attrs['aria-disabled'] = 'true';
    }

    if (data.id == null) {
      delete attrs['aria-selected'];
    }

    if (data._resultId != null) {
      option.id = data._resultId;
    }

    if (data.title) {
      option.title = data.title;
    }

    if (data.children) {
      attrs.role = 'group';
      attrs['aria-label'] = data.text;
      delete attrs['aria-selected'];
    }

    for (var attr in attrs) {
      var val = attrs[attr];

      option.setAttribute(attr, val);
    }

    if (data.children) {
      var $option = $(option);

      var label = document.createElement('strong');
      label.className = 'select2-results__group';

      var $label = $(label);
      this.template(data, label);

      var $children = [];

      for (var c = 0; c < data.children.length; c++) {
        var child = data.children[c];

        var $child = this.option(child);

        $children.push($child);
      }

      var $childrenContainer = $('<ul></ul>', {
        'class': 'select2-results__options select2-results__options--nested'
      });

      $childrenContainer.append($children);

      $option.append(label);
      $option.append($childrenContainer);
    } else {
      this.template(data, option);
    }

    $.data(option, 'data', data);

    return option;
  };

  Results.prototype.bind = function (container, $container) {
    var self = this;

    var id = container.id + '-results';

    this.$results.attr('id', id);

    container.on('results:all', function (params) {
      self.clear();
      self.append(params.data);

      if (container.isOpen()) {
        self.setClasses();
        self.highlightFirstItem();
      }
    });

    container.on('results:append', function (params) {
      self.append(params.data);

      if (container.isOpen()) {
        self.setClasses();
      }
    });

    container.on('query', function (params) {
      self.hideMessages();
      self.showLoading(params);
    });

    container.on('select', function () {
      if (!container.isOpen()) {
        return;
      }

      self.setClasses();
      self.highlightFirstItem();
    });

    container.on('unselect', function () {
      if (!container.isOpen()) {
        return;
      }

      self.setClasses();
      self.highlightFirstItem();
    });

    container.on('open', function () {
      // When the dropdown is open, aria-expended="true"
      self.$results.attr('aria-expanded', 'true');
      self.$results.attr('aria-hidden', 'false');

      self.setClasses();
      self.ensureHighlightVisible();
    });

    container.on('close', function () {
      // When the dropdown is closed, aria-expended="false"
      self.$results.attr('aria-expanded', 'false');
      self.$results.attr('aria-hidden', 'true');
      self.$results.removeAttr('aria-activedescendant');
    });

    container.on('results:toggle', function () {
      var $highlighted = self.getHighlightedResults();

      if ($highlighted.length === 0) {
        return;
      }

      $highlighted.trigger('mouseup');
    });

    container.on('results:select', function () {
      var $highlighted = self.getHighlightedResults();

      if ($highlighted.length === 0) {
        return;
      }

      var data = $highlighted.data('data');

      if ($highlighted.attr('aria-selected') == 'true') {
        self.trigger('close', {});
      } else {
        self.trigger('select', {
          data: data
        });
      }
    });

    container.on('results:previous', function () {
      var $highlighted = self.getHighlightedResults();

      var $options = self.$results.find('[aria-selected]');

      var currentIndex = $options.index($highlighted);

      // If we are already at te top, don't move further
      if (currentIndex === 0) {
        return;
      }

      var nextIndex = currentIndex - 1;

      // If none are highlighted, highlight the first
      if ($highlighted.length === 0) {
        nextIndex = 0;
      }

      var $next = $options.eq(nextIndex);

      $next.trigger('mouseenter');

      var currentOffset = self.$results.offset().top;
      var nextTop = $next.offset().top;
      var nextOffset = self.$results.scrollTop() + (nextTop - currentOffset);

      if (nextIndex === 0) {
        self.$results.scrollTop(0);
      } else if (nextTop - currentOffset < 0) {
        self.$results.scrollTop(nextOffset);
      }
    });

    container.on('results:next', function () {
      var $highlighted = self.getHighlightedResults();

      var $options = self.$results.find('[aria-selected]');

      var currentIndex = $options.index($highlighted);

      var nextIndex = currentIndex + 1;

      // If we are at the last option, stay there
      if (nextIndex >= $options.length) {
        return;
      }

      var $next = $options.eq(nextIndex);

      $next.trigger('mouseenter');

      var currentOffset = self.$results.offset().top +
        self.$results.outerHeight(false);
      var nextBottom = $next.offset().top + $next.outerHeight(false);
      var nextOffset = self.$results.scrollTop() + nextBottom - currentOffset;

      if (nextIndex === 0) {
        self.$results.scrollTop(0);
      } else if (nextBottom > currentOffset) {
        self.$results.scrollTop(nextOffset);
      }
    });

    container.on('results:focus', function (params) {
      params.element.addClass('select2-results__option--highlighted');
    });

    container.on('results:message', function (params) {
      self.displayMessage(params);
    });

    if ($.fn.mousewheel) {
      this.$results.on('mousewheel', function (e) {
        var top = self.$results.scrollTop();

        var bottom = self.$results.get(0).scrollHeight - top + e.deltaY;

        var isAtTop = e.deltaY > 0 && top - e.deltaY <= 0;
        var isAtBottom = e.deltaY < 0 && bottom <= self.$results.height();

        if (isAtTop) {
          self.$results.scrollTop(0);

          e.preventDefault();
          e.stopPropagation();
        } else if (isAtBottom) {
          self.$results.scrollTop(
            self.$results.get(0).scrollHeight - self.$results.height()
          );

          e.preventDefault();
          e.stopPropagation();
        }
      });
    }

    this.$results.on('mouseup', '.select2-results__option[aria-selected]',
      function (evt) {
      var $this = $(this);

      var data = $this.data('data');

      if ($this.attr('aria-selected') === 'true') {
        if (self.options.get('multiple')) {
          self.trigger('unselect', {
            originalEvent: evt,
            data: data
          });
        } else {
          self.trigger('close', {});
        }

        return;
      }

      self.trigger('select', {
        originalEvent: evt,
        data: data
      });
    });

    this.$results.on('mouseenter', '.select2-results__option[aria-selected]',
      function (evt) {
      var data = $(this).data('data');

      self.getHighlightedResults()
          .removeClass('select2-results__option--highlighted');

      self.trigger('results:focus', {
        data: data,
        element: $(this)
      });
    });
  };

  Results.prototype.getHighlightedResults = function () {
    var $highlighted = this.$results
    .find('.select2-results__option--highlighted');

    return $highlighted;
  };

  Results.prototype.destroy = function () {
    this.$results.remove();
  };

  Results.prototype.ensureHighlightVisible = function () {
    var $highlighted = this.getHighlightedResults();

    if ($highlighted.length === 0) {
      return;
    }

    var $options = this.$results.find('[aria-selected]');

    var currentIndex = $options.index($highlighted);

    var currentOffset = this.$results.offset().top;
    var nextTop = $highlighted.offset().top;
    var nextOffset = this.$results.scrollTop() + (nextTop - currentOffset);

    var offsetDelta = nextTop - currentOffset;
    nextOffset -= $highlighted.outerHeight(false) * 2;

    if (currentIndex <= 2) {
      this.$results.scrollTop(0);
    } else if (offsetDelta > this.$results.outerHeight() || offsetDelta < 0) {
      this.$results.scrollTop(nextOffset);
    }
  };

  Results.prototype.template = function (result, container) {
    var template = this.options.get('templateResult');
    var escapeMarkup = this.options.get('escapeMarkup');

    var content = template(result, container);

    if (content == null) {
      container.style.display = 'none';
    } else if (typeof content === 'string') {
      container.innerHTML = escapeMarkup(content);
    } else {
      $(container).append(content);
    }
  };

  return Results;
});

S2.define('select2/keys',[

], function () {
  var KEYS = {
    BACKSPACE: 8,
    TAB: 9,
    ENTER: 13,
    SHIFT: 16,
    CTRL: 17,
    ALT: 18,
    ESC: 27,
    SPACE: 32,
    PAGE_UP: 33,
    PAGE_DOWN: 34,
    END: 35,
    HOME: 36,
    LEFT: 37,
    UP: 38,
    RIGHT: 39,
    DOWN: 40,
    DELETE: 46
  };

  return KEYS;
});

S2.define('select2/selection/base',[
  'jquery',
  '../utils',
  '../keys'
], function ($, Utils, KEYS) {
  function BaseSelection ($element, options) {
    this.$element = $element;
    this.options = options;

    BaseSelection.__super__.constructor.call(this);
  }

  Utils.Extend(BaseSelection, Utils.Observable);

  BaseSelection.prototype.render = function () {
    var $selection = $(
      '<span class="select2-selection" role="combobox" ' +
      ' aria-haspopup="true" aria-expanded="false">' +
      '</span>'
    );

    this._tabindex = 0;

    if (this.$element.data('old-tabindex') != null) {
      this._tabindex = this.$element.data('old-tabindex');
    } else if (this.$element.attr('tabindex') != null) {
      this._tabindex = this.$element.attr('tabindex');
    }

    $selection.attr('title', this.$element.attr('title'));
    $selection.attr('tabindex', this._tabindex);

    this.$selection = $selection;

    return $selection;
  };

  BaseSelection.prototype.bind = function (container, $container) {
    var self = this;

    var id = container.id + '-container';
    var resultsId = container.id + '-results';

    this.container = container;

    this.$selection.on('focus', function (evt) {
      self.trigger('focus', evt);
    });

    this.$selection.on('blur', function (evt) {
      self._handleBlur(evt);
    });

    this.$selection.on('keydown', function (evt) {
      self.trigger('keypress', evt);

      if (evt.which === KEYS.SPACE) {
        evt.preventDefault();
      }
    });

    container.on('results:focus', function (params) {
      self.$selection.attr('aria-activedescendant', params.data._resultId);
    });

    container.on('selection:update', function (params) {
      self.update(params.data);
    });

    container.on('open', function () {
      // When the dropdown is open, aria-expanded="true"
      self.$selection.attr('aria-expanded', 'true');
      self.$selection.attr('aria-owns', resultsId);

      self._attachCloseHandler(container);
    });

    container.on('close', function () {
      // When the dropdown is closed, aria-expanded="false"
      self.$selection.attr('aria-expanded', 'false');
      self.$selection.removeAttr('aria-activedescendant');
      self.$selection.removeAttr('aria-owns');

      self.$selection.focus();

      self._detachCloseHandler(container);
    });

    container.on('enable', function () {
      self.$selection.attr('tabindex', self._tabindex);
    });

    container.on('disable', function () {
      self.$selection.attr('tabindex', '-1');
    });
  };

  BaseSelection.prototype._handleBlur = function (evt) {
    var self = this;

    // This needs to be delayed as the active element is the body when the tab
    // key is pressed, possibly along with others.
    window.setTimeout(function () {
      // Don't trigger `blur` if the focus is still in the selection
      if (
        (document.activeElement == self.$selection[0]) ||
        ($.contains(self.$selection[0], document.activeElement))
      ) {
        return;
      }

      self.trigger('blur', evt);
    }, 1);
  };

  BaseSelection.prototype._attachCloseHandler = function (container) {
    var self = this;

    $(document.body).on('mousedown.select2.' + container.id, function (e) {
      var $target = $(e.target);

      var $select = $target.closest('.select2');

      var $all = $('.select2.select2-container--open');

      $all.each(function () {
        var $this = $(this);

        if (this == $select[0]) {
          return;
        }

        var $element = $this.data('element');

        $element.select2('close');
      });
    });
  };

  BaseSelection.prototype._detachCloseHandler = function (container) {
    $(document.body).off('mousedown.select2.' + container.id);
  };

  BaseSelection.prototype.position = function ($selection, $container) {
    var $selectionContainer = $container.find('.selection');
    $selectionContainer.append($selection);
  };

  BaseSelection.prototype.destroy = function () {
    this._detachCloseHandler(this.container);
  };

  BaseSelection.prototype.update = function (data) {
    throw new Error('The `update` method must be defined in child classes.');
  };

  return BaseSelection;
});

S2.define('select2/selection/single',[
  'jquery',
  './base',
  '../utils',
  '../keys'
], function ($, BaseSelection, Utils, KEYS) {
  function SingleSelection () {
    SingleSelection.__super__.constructor.apply(this, arguments);
  }

  Utils.Extend(SingleSelection, BaseSelection);

  SingleSelection.prototype.render = function () {
    var $selection = SingleSelection.__super__.render.call(this);

    $selection.addClass('select2-selection--single');

    $selection.html(
      '<span class="select2-selection__rendered"></span>' +
      '<span class="select2-selection__arrow" role="presentation">' +
        '<b role="presentation"></b>' +
      '</span>'
    );

    return $selection;
  };

  SingleSelection.prototype.bind = function (container, $container) {
    var self = this;

    SingleSelection.__super__.bind.apply(this, arguments);

    var id = container.id + '-container';

    this.$selection.find('.select2-selection__rendered').attr('id', id);
    this.$selection.attr('aria-labelledby', id);

    this.$selection.on('mousedown', function (evt) {
      // Only respond to left clicks
      if (evt.which !== 1) {
        return;
      }

      self.trigger('toggle', {
        originalEvent: evt
      });
    });

    this.$selection.on('focus', function (evt) {
      // User focuses on the container
    });

    this.$selection.on('blur', function (evt) {
      // User exits the container
    });

    container.on('focus', function (evt) {
      if (!container.isOpen()) {
        self.$selection.focus();
      }
    });

    container.on('selection:update', function (params) {
      self.update(params.data);
    });
  };

  SingleSelection.prototype.clear = function () {
    this.$selection.find('.select2-selection__rendered').empty();
  };

  SingleSelection.prototype.display = function (data, container) {
    var template = this.options.get('templateSelection');
    var escapeMarkup = this.options.get('escapeMarkup');

    return escapeMarkup(template(data, container));
  };

  SingleSelection.prototype.selectionContainer = function () {
    return $('<span></span>');
  };

  SingleSelection.prototype.update = function (data) {
    if (data.length === 0) {
      this.clear();
      return;
    }

    var selection = data[0];

    var $rendered = this.$selection.find('.select2-selection__rendered');
    var formatted = this.display(selection, $rendered);

    $rendered.empty().append(formatted);
    $rendered.prop('title', selection.title || selection.text);
  };

  return SingleSelection;
});

S2.define('select2/selection/multiple',[
  'jquery',
  './base',
  '../utils'
], function ($, BaseSelection, Utils) {
  function MultipleSelection ($element, options) {
    MultipleSelection.__super__.constructor.apply(this, arguments);
  }

  Utils.Extend(MultipleSelection, BaseSelection);

  MultipleSelection.prototype.render = function () {
    var $selection = MultipleSelection.__super__.render.call(this);

    $selection.addClass('select2-selection--multiple');

    $selection.html(
      '<ul class="select2-selection__rendered"></ul>'
    );

    return $selection;
  };

  MultipleSelection.prototype.bind = function (container, $container) {
    var self = this;

    MultipleSelection.__super__.bind.apply(this, arguments);

    this.$selection.on('click', function (evt) {
      self.trigger('toggle', {
        originalEvent: evt
      });
    });

    this.$selection.on(
      'click',
      '.select2-selection__choice__remove',
      function (evt) {
        // Ignore the event if it is disabled
        if (self.options.get('disabled')) {
          return;
        }

        var $remove = $(this);
        var $selection = $remove.parent();

        var data = $selection.data('data');

        self.trigger('unselect', {
          originalEvent: evt,
          data: data
        });
      }
    );
  };

  MultipleSelection.prototype.clear = function () {
    this.$selection.find('.select2-selection__rendered').empty();
  };

  MultipleSelection.prototype.display = function (data, container) {
    var template = this.options.get('templateSelection');
    var escapeMarkup = this.options.get('escapeMarkup');

    return escapeMarkup(template(data, container));
  };

  MultipleSelection.prototype.selectionContainer = function () {
    var $container = $(
      '<li class="select2-selection__choice">' +
        '<span class="select2-selection__choice__remove" role="presentation">' +
          '&times;' +
        '</span>' +
      '</li>'
    );

    return $container;
  };

  MultipleSelection.prototype.update = function (data) {
    this.clear();

    if (data.length === 0) {
      return;
    }

    var $selections = [];

    for (var d = 0; d < data.length; d++) {
      var selection = data[d];

      var $selection = this.selectionContainer();
      var formatted = this.display(selection, $selection);

      $selection.append(formatted);
      $selection.prop('title', selection.title || selection.text);

      $selection.data('data', selection);

      $selections.push($selection);
    }

    var $rendered = this.$selection.find('.select2-selection__rendered');

    Utils.appendMany($rendered, $selections);
  };

  return MultipleSelection;
});

S2.define('select2/selection/placeholder',[
  '../utils'
], function (Utils) {
  function Placeholder (decorated, $element, options) {
    this.placeholder = this.normalizePlaceholder(options.get('placeholder'));

    decorated.call(this, $element, options);
  }

  Placeholder.prototype.normalizePlaceholder = function (_, placeholder) {
    if (typeof placeholder === 'string') {
      placeholder = {
        id: '',
        text: placeholder
      };
    }

    return placeholder;
  };

  Placeholder.prototype.createPlaceholder = function (decorated, placeholder) {
    var $placeholder = this.selectionContainer();

    $placeholder.html(this.display(placeholder));
    $placeholder.addClass('select2-selection__placeholder')
                .removeClass('select2-selection__choice');

    return $placeholder;
  };

  Placeholder.prototype.update = function (decorated, data) {
    var singlePlaceholder = (
      data.length == 1 && data[0].id != this.placeholder.id
    );
    var multipleSelections = data.length > 1;

    if (multipleSelections || singlePlaceholder) {
      return decorated.call(this, data);
    }

    this.clear();

    var $placeholder = this.createPlaceholder(this.placeholder);

    this.$selection.find('.select2-selection__rendered').append($placeholder);
  };

  return Placeholder;
});

S2.define('select2/selection/allowClear',[
  'jquery',
  '../keys'
], function ($, KEYS) {
  function AllowClear () { }

  AllowClear.prototype.bind = function (decorated, container, $container) {
    var self = this;

    decorated.call(this, container, $container);

    if (this.placeholder == null) {
      if (this.options.get('debug') && window.console && console.error) {
        console.error(
          'Select2: The `allowClear` option should be used in combination ' +
          'with the `placeholder` option.'
        );
      }
    }

    this.$selection.on('mousedown', '.select2-selection__clear',
      function (evt) {
        self._handleClear(evt);
    });

    container.on('keypress', function (evt) {
      self._handleKeyboardClear(evt, container);
    });
  };

  AllowClear.prototype._handleClear = function (_, evt) {
    // Ignore the event if it is disabled
    if (this.options.get('disabled')) {
      return;
    }

    var $clear = this.$selection.find('.select2-selection__clear');

    // Ignore the event if nothing has been selected
    if ($clear.length === 0) {
      return;
    }

    evt.stopPropagation();

    var data = $clear.data('data');

    for (var d = 0; d < data.length; d++) {
      var unselectData = {
        data: data[d]
      };

      // Trigger the `unselect` event, so people can prevent it from being
      // cleared.
      this.trigger('unselect', unselectData);

      // If the event was prevented, don't clear it out.
      if (unselectData.prevented) {
        return;
      }
    }

    this.$element.val(this.placeholder.id).trigger('change');

    this.trigger('toggle', {});
  };

  AllowClear.prototype._handleKeyboardClear = function (_, evt, container) {
    if (container.isOpen()) {
      return;
    }

    if (evt.which == KEYS.DELETE || evt.which == KEYS.BACKSPACE) {
      this._handleClear(evt);
    }
  };

  AllowClear.prototype.update = function (decorated, data) {
    decorated.call(this, data);

    if (this.$selection.find('.select2-selection__placeholder').length > 0 ||
        data.length === 0) {
      return;
    }

    var $remove = $(
      '<span class="select2-selection__clear">' +
        '&times;' +
      '</span>'
    );
    $remove.data('data', data);

    this.$selection.find('.select2-selection__rendered').prepend($remove);
  };

  return AllowClear;
});

S2.define('select2/selection/search',[
  'jquery',
  '../utils',
  '../keys'
], function ($, Utils, KEYS) {
  function Search (decorated, $element, options) {
    decorated.call(this, $element, options);
  }

  Search.prototype.render = function (decorated) {
    var $search = $(
      '<li class="select2-search select2-search--inline">' +
        '<input class="select2-search__field" type="search" tabindex="-1"' +
        ' autocomplete="off" autocorrect="off" autocapitalize="off"' +
        ' spellcheck="false" role="textbox" aria-autocomplete="list" />' +
      '</li>'
    );

    this.$searchContainer = $search;
    this.$search = $search.find('input');

    var $rendered = decorated.call(this);

    this._transferTabIndex();

    return $rendered;
  };

  Search.prototype.bind = function (decorated, container, $container) {
    var self = this;

    decorated.call(this, container, $container);

    container.on('open', function () {
      self.$search.trigger('focus');
    });

    container.on('close', function () {
      self.$search.val('');
      self.$search.removeAttr('aria-activedescendant');
      self.$search.trigger('focus');
    });

    container.on('enable', function () {
      self.$search.prop('disabled', false);

      self._transferTabIndex();
    });

    container.on('disable', function () {
      self.$search.prop('disabled', true);
    });

    container.on('focus', function (evt) {
      self.$search.trigger('focus');
    });

    container.on('results:focus', function (params) {
      self.$search.attr('aria-activedescendant', params.id);
    });

    this.$selection.on('focusin', '.select2-search--inline', function (evt) {
      self.trigger('focus', evt);
    });

    this.$selection.on('focusout', '.select2-search--inline', function (evt) {
      self._handleBlur(evt);
    });

    this.$selection.on('keydown', '.select2-search--inline', function (evt) {
      evt.stopPropagation();

      self.trigger('keypress', evt);

      self._keyUpPrevented = evt.isDefaultPrevented();

      var key = evt.which;
/* 
      if (key === KEYS.BACKSPACE && self.$search.val() === '') {
        var $previousChoice = self.$searchContainer
          .prev('.select2-selection__choice');

        if ($previousChoice.length > 0) {
          var item = $previousChoice.data('data');

          self.searchRemoveChoice(item);

          evt.preventDefault();
        }
      } */
    });

    // Try to detect the IE version should the `documentMode` property that
    // is stored on the document. This is only implemented in IE and is
    // slightly cleaner than doing a user agent check.
    // This property is not available in Edge, but Edge also doesn't have
    // this bug.
    var msie = document.documentMode;
    var disableInputEvents = msie && msie <= 11;

    // Workaround for browsers which do not support the `input` event
    // This will prevent double-triggering of events for browsers which support
    // both the `keyup` and `input` events.
    this.$selection.on(
      'input.searchcheck',
      '.select2-search--inline',
      function (evt) {
        // IE will trigger the `input` event when a placeholder is used on a
        // search box. To get around this issue, we are forced to ignore all
        // `input` events in IE and keep using `keyup`.
        if (disableInputEvents) {
          self.$selection.off('input.search input.searchcheck');
          return;
        }

        // Unbind the duplicated `keyup` event
        self.$selection.off('keyup.search');
      }
    );

    this.$selection.on(
      'keyup.search input.search',
      '.select2-search--inline',
      function (evt) {
        // IE will trigger the `input` event when a placeholder is used on a
        // search box. To get around this issue, we are forced to ignore all
        // `input` events in IE and keep using `keyup`.
        if (disableInputEvents && evt.type === 'input') {
          self.$selection.off('input.search input.searchcheck');
          return;
        }

        var key = evt.which;

        // We can freely ignore events from modifier keys
        if (key == KEYS.SHIFT || key == KEYS.CTRL || key == KEYS.ALT) {
          return;
        }

        // Tabbing will be handled during the `keydown` phase
        if (key == KEYS.TAB) {
          return;
        }

        self.handleSearch(evt);
      }
    );
  };

  /**
   * This method will transfer the tabindex attribute from the rendered
   * selection to the search box. This allows for the search box to be used as
   * the primary focus instead of the selection container.
   *
   * @private
   */
  Search.prototype._transferTabIndex = function (decorated) {
    this.$search.attr('tabindex', this.$selection.attr('tabindex'));
    this.$selection.attr('tabindex', '-1');
  };

  Search.prototype.createPlaceholder = function (decorated, placeholder) {
    this.$search.attr('placeholder', placeholder.text);
  };

  Search.prototype.update = function (decorated, data) {
    var searchHadFocus = this.$search[0] == document.activeElement;

    this.$search.attr('placeholder', '');

    decorated.call(this, data);

    this.$selection.find('.select2-selection__rendered')
                   .append(this.$searchContainer);

    this.resizeSearch();
    if (searchHadFocus) {
      this.$search.focus();
    }
  };

  Search.prototype.handleSearch = function () {
    this.resizeSearch();

    if (!this._keyUpPrevented) {
      var input = this.$search.val();

      this.trigger('query', {
        term: input
      });
    }

    this._keyUpPrevented = false;
  };

  Search.prototype.searchRemoveChoice = function (decorated, item) {
    this.trigger('unselect', {
      data: item
    });

    this.$search.val(item.text);
    this.handleSearch();
  };

  Search.prototype.resizeSearch = function () {
    this.$search.css('width', '25px');

    var width = '';

    if (this.$search.attr('placeholder') !== '') {
      width = this.$selection.find('.select2-selection__rendered').innerWidth();
    } else {
      var minimumWidth = this.$search.val().length + 1;

      width = (minimumWidth * 0.75) + 'em';
    }

    this.$search.css('width', width);
  };

  return Search;
});

S2.define('select2/selection/eventRelay',[
  'jquery'
], function ($) {
  function EventRelay () { }

  EventRelay.prototype.bind = function (decorated, container, $container) {
    var self = this;
    var relayEvents = [
      'open', 'opening',
      'close', 'closing',
      'select', 'selecting',
      'unselect', 'unselecting'
    ];

    var preventableEvents = ['opening', 'closing', 'selecting', 'unselecting'];

    decorated.call(this, container, $container);

    container.on('*', function (name, params) {
      // Ignore events that should not be relayed
      if ($.inArray(name, relayEvents) === -1) {
        return;
      }

      // The parameters should always be an object
      params = params || {};

      // Generate the jQuery event for the Select2 event
      var evt = $.Event('select2:' + name, {
        params: params
      });

      self.$element.trigger(evt);

      // Only handle preventable events if it was one
      if ($.inArray(name, preventableEvents) === -1) {
        return;
      }

      params.prevented = evt.isDefaultPrevented();
    });
  };

  return EventRelay;
});

S2.define('select2/translation',[
  'jquery',
  'require'
], function ($, require) {
  function Translation (dict) {
    this.dict = dict || {};
  }

  Translation.prototype.all = function () {
    return this.dict;
  };

  Translation.prototype.get = function (key) {
    return this.dict[key];
  };

  Translation.prototype.extend = function (translation) {
    this.dict = $.extend({}, translation.all(), this.dict);
  };

  // Static functions

  Translation._cache = {};

  Translation.loadPath = function (path) {
    if (!(path in Translation._cache)) {
      var translations = require(path);

      Translation._cache[path] = translations;
    }

    return new Translation(Translation._cache[path]);
  };

  return Translation;
});

S2.define('select2/diacritics',[

], function () {
  var diacritics = {
    '\u24B6': 'A',
    '\uFF21': 'A',
    '\u00C0': 'A',
    '\u00C1': 'A',
    '\u00C2': 'A',
    '\u1EA6': 'A',
    '\u1EA4': 'A',
    '\u1EAA': 'A',
    '\u1EA8': 'A',
    '\u00C3': 'A',
    '\u0100': 'A',
    '\u0102': 'A',
    '\u1EB0': 'A',
    '\u1EAE': 'A',
    '\u1EB4': 'A',
    '\u1EB2': 'A',
    '\u0226': 'A',
    '\u01E0': 'A',
    '\u00C4': 'A',
    '\u01DE': 'A',
    '\u1EA2': 'A',
    '\u00C5': 'A',
    '\u01FA': 'A',
    '\u01CD': 'A',
    '\u0200': 'A',
    '\u0202': 'A',
    '\u1EA0': 'A',
    '\u1EAC': 'A',
    '\u1EB6': 'A',
    '\u1E00': 'A',
    '\u0104': 'A',
    '\u023A': 'A',
    '\u2C6F': 'A',
    '\uA732': 'AA',
    '\u00C6': 'AE',
    '\u01FC': 'AE',
    '\u01E2': 'AE',
    '\uA734': 'AO',
    '\uA736': 'AU',
    '\uA738': 'AV',
    '\uA73A': 'AV',
    '\uA73C': 'AY',
    '\u24B7': 'B',
    '\uFF22': 'B',
    '\u1E02': 'B',
    '\u1E04': 'B',
    '\u1E06': 'B',
    '\u0243': 'B',
    '\u0182': 'B',
    '\u0181': 'B',
    '\u24B8': 'C',
    '\uFF23': 'C',
    '\u0106': 'C',
    '\u0108': 'C',
    '\u010A': 'C',
    '\u010C': 'C',
    '\u00C7': 'C',
    '\u1E08': 'C',
    '\u0187': 'C',
    '\u023B': 'C',
    '\uA73E': 'C',
    '\u24B9': 'D',
    '\uFF24': 'D',
    '\u1E0A': 'D',
    '\u010E': 'D',
    '\u1E0C': 'D',
    '\u1E10': 'D',
    '\u1E12': 'D',
    '\u1E0E': 'D',
    '\u0110': 'D',
    '\u018B': 'D',
    '\u018A': 'D',
    '\u0189': 'D',
    '\uA779': 'D',
    '\u01F1': 'DZ',
    '\u01C4': 'DZ',
    '\u01F2': 'Dz',
    '\u01C5': 'Dz',
    '\u24BA': 'E',
    '\uFF25': 'E',
    '\u00C8': 'E',
    '\u00C9': 'E',
    '\u00CA': 'E',
    '\u1EC0': 'E',
    '\u1EBE': 'E',
    '\u1EC4': 'E',
    '\u1EC2': 'E',
    '\u1EBC': 'E',
    '\u0112': 'E',
    '\u1E14': 'E',
    '\u1E16': 'E',
    '\u0114': 'E',
    '\u0116': 'E',
    '\u00CB': 'E',
    '\u1EBA': 'E',
    '\u011A': 'E',
    '\u0204': 'E',
    '\u0206': 'E',
    '\u1EB8': 'E',
    '\u1EC6': 'E',
    '\u0228': 'E',
    '\u1E1C': 'E',
    '\u0118': 'E',
    '\u1E18': 'E',
    '\u1E1A': 'E',
    '\u0190': 'E',
    '\u018E': 'E',
    '\u24BB': 'F',
    '\uFF26': 'F',
    '\u1E1E': 'F',
    '\u0191': 'F',
    '\uA77B': 'F',
    '\u24BC': 'G',
    '\uFF27': 'G',
    '\u01F4': 'G',
    '\u011C': 'G',
    '\u1E20': 'G',
    '\u011E': 'G',
    '\u0120': 'G',
    '\u01E6': 'G',
    '\u0122': 'G',
    '\u01E4': 'G',
    '\u0193': 'G',
    '\uA7A0': 'G',
    '\uA77D': 'G',
    '\uA77E': 'G',
    '\u24BD': 'H',
    '\uFF28': 'H',
    '\u0124': 'H',
    '\u1E22': 'H',
    '\u1E26': 'H',
    '\u021E': 'H',
    '\u1E24': 'H',
    '\u1E28': 'H',
    '\u1E2A': 'H',
    '\u0126': 'H',
    '\u2C67': 'H',
    '\u2C75': 'H',
    '\uA78D': 'H',
    '\u24BE': 'I',
    '\uFF29': 'I',
    '\u00CC': 'I',
    '\u00CD': 'I',
    '\u00CE': 'I',
    '\u0128': 'I',
    '\u012A': 'I',
    '\u012C': 'I',
    '\u0130': 'I',
    '\u00CF': 'I',
    '\u1E2E': 'I',
    '\u1EC8': 'I',
    '\u01CF': 'I',
    '\u0208': 'I',
    '\u020A': 'I',
    '\u1ECA': 'I',
    '\u012E': 'I',
    '\u1E2C': 'I',
    '\u0197': 'I',
    '\u24BF': 'J',
    '\uFF2A': 'J',
    '\u0134': 'J',
    '\u0248': 'J',
    '\u24C0': 'K',
    '\uFF2B': 'K',
    '\u1E30': 'K',
    '\u01E8': 'K',
    '\u1E32': 'K',
    '\u0136': 'K',
    '\u1E34': 'K',
    '\u0198': 'K',
    '\u2C69': 'K',
    '\uA740': 'K',
    '\uA742': 'K',
    '\uA744': 'K',
    '\uA7A2': 'K',
    '\u24C1': 'L',
    '\uFF2C': 'L',
    '\u013F': 'L',
    '\u0139': 'L',
    '\u013D': 'L',
    '\u1E36': 'L',
    '\u1E38': 'L',
    '\u013B': 'L',
    '\u1E3C': 'L',
    '\u1E3A': 'L',
    '\u0141': 'L',
    '\u023D': 'L',
    '\u2C62': 'L',
    '\u2C60': 'L',
    '\uA748': 'L',
    '\uA746': 'L',
    '\uA780': 'L',
    '\u01C7': 'LJ',
    '\u01C8': 'Lj',
    '\u24C2': 'M',
    '\uFF2D': 'M',
    '\u1E3E': 'M',
    '\u1E40': 'M',
    '\u1E42': 'M',
    '\u2C6E': 'M',
    '\u019C': 'M',
    '\u24C3': 'N',
    '\uFF2E': 'N',
    '\u01F8': 'N',
    '\u0143': 'N',
    '\u00D1': 'N',
    '\u1E44': 'N',
    '\u0147': 'N',
    '\u1E46': 'N',
    '\u0145': 'N',
    '\u1E4A': 'N',
    '\u1E48': 'N',
    '\u0220': 'N',
    '\u019D': 'N',
    '\uA790': 'N',
    '\uA7A4': 'N',
    '\u01CA': 'NJ',
    '\u01CB': 'Nj',
    '\u24C4': 'O',
    '\uFF2F': 'O',
    '\u00D2': 'O',
    '\u00D3': 'O',
    '\u00D4': 'O',
    '\u1ED2': 'O',
    '\u1ED0': 'O',
    '\u1ED6': 'O',
    '\u1ED4': 'O',
    '\u00D5': 'O',
    '\u1E4C': 'O',
    '\u022C': 'O',
    '\u1E4E': 'O',
    '\u014C': 'O',
    '\u1E50': 'O',
    '\u1E52': 'O',
    '\u014E': 'O',
    '\u022E': 'O',
    '\u0230': 'O',
    '\u00D6': 'O',
    '\u022A': 'O',
    '\u1ECE': 'O',
    '\u0150': 'O',
    '\u01D1': 'O',
    '\u020C': 'O',
    '\u020E': 'O',
    '\u01A0': 'O',
    '\u1EDC': 'O',
    '\u1EDA': 'O',
    '\u1EE0': 'O',
    '\u1EDE': 'O',
    '\u1EE2': 'O',
    '\u1ECC': 'O',
    '\u1ED8': 'O',
    '\u01EA': 'O',
    '\u01EC': 'O',
    '\u00D8': 'O',
    '\u01FE': 'O',
    '\u0186': 'O',
    '\u019F': 'O',
    '\uA74A': 'O',
    '\uA74C': 'O',
    '\u01A2': 'OI',
    '\uA74E': 'OO',
    '\u0222': 'OU',
    '\u24C5': 'P',
    '\uFF30': 'P',
    '\u1E54': 'P',
    '\u1E56': 'P',
    '\u01A4': 'P',
    '\u2C63': 'P',
    '\uA750': 'P',
    '\uA752': 'P',
    '\uA754': 'P',
    '\u24C6': 'Q',
    '\uFF31': 'Q',
    '\uA756': 'Q',
    '\uA758': 'Q',
    '\u024A': 'Q',
    '\u24C7': 'R',
    '\uFF32': 'R',
    '\u0154': 'R',
    '\u1E58': 'R',
    '\u0158': 'R',
    '\u0210': 'R',
    '\u0212': 'R',
    '\u1E5A': 'R',
    '\u1E5C': 'R',
    '\u0156': 'R',
    '\u1E5E': 'R',
    '\u024C': 'R',
    '\u2C64': 'R',
    '\uA75A': 'R',
    '\uA7A6': 'R',
    '\uA782': 'R',
    '\u24C8': 'S',
    '\uFF33': 'S',
    '\u1E9E': 'S',
    '\u015A': 'S',
    '\u1E64': 'S',
    '\u015C': 'S',
    '\u1E60': 'S',
    '\u0160': 'S',
    '\u1E66': 'S',
    '\u1E62': 'S',
    '\u1E68': 'S',
    '\u0218': 'S',
    '\u015E': 'S',
    '\u2C7E': 'S',
    '\uA7A8': 'S',
    '\uA784': 'S',
    '\u24C9': 'T',
    '\uFF34': 'T',
    '\u1E6A': 'T',
    '\u0164': 'T',
    '\u1E6C': 'T',
    '\u021A': 'T',
    '\u0162': 'T',
    '\u1E70': 'T',
    '\u1E6E': 'T',
    '\u0166': 'T',
    '\u01AC': 'T',
    '\u01AE': 'T',
    '\u023E': 'T',
    '\uA786': 'T',
    '\uA728': 'TZ',
    '\u24CA': 'U',
    '\uFF35': 'U',
    '\u00D9': 'U',
    '\u00DA': 'U',
    '\u00DB': 'U',
    '\u0168': 'U',
    '\u1E78': 'U',
    '\u016A': 'U',
    '\u1E7A': 'U',
    '\u016C': 'U',
    '\u00DC': 'U',
    '\u01DB': 'U',
    '\u01D7': 'U',
    '\u01D5': 'U',
    '\u01D9': 'U',
    '\u1EE6': 'U',
    '\u016E': 'U',
    '\u0170': 'U',
    '\u01D3': 'U',
    '\u0214': 'U',
    '\u0216': 'U',
    '\u01AF': 'U',
    '\u1EEA': 'U',
    '\u1EE8': 'U',
    '\u1EEE': 'U',
    '\u1EEC': 'U',
    '\u1EF0': 'U',
    '\u1EE4': 'U',
    '\u1E72': 'U',
    '\u0172': 'U',
    '\u1E76': 'U',
    '\u1E74': 'U',
    '\u0244': 'U',
    '\u24CB': 'V',
    '\uFF36': 'V',
    '\u1E7C': 'V',
    '\u1E7E': 'V',
    '\u01B2': 'V',
    '\uA75E': 'V',
    '\u0245': 'V',
    '\uA760': 'VY',
    '\u24CC': 'W',
    '\uFF37': 'W',
    '\u1E80': 'W',
    '\u1E82': 'W',
    '\u0174': 'W',
    '\u1E86': 'W',
    '\u1E84': 'W',
    '\u1E88': 'W',
    '\u2C72': 'W',
    '\u24CD': 'X',
    '\uFF38': 'X',
    '\u1E8A': 'X',
    '\u1E8C': 'X',
    '\u24CE': 'Y',
    '\uFF39': 'Y',
    '\u1EF2': 'Y',
    '\u00DD': 'Y',
    '\u0176': 'Y',
    '\u1EF8': 'Y',
    '\u0232': 'Y',
    '\u1E8E': 'Y',
    '\u0178': 'Y',
    '\u1EF6': 'Y',
    '\u1EF4': 'Y',
    '\u01B3': 'Y',
    '\u024E': 'Y',
    '\u1EFE': 'Y',
    '\u24CF': 'Z',
    '\uFF3A': 'Z',
    '\u0179': 'Z',
    '\u1E90': 'Z',
    '\u017B': 'Z',
    '\u017D': 'Z',
    '\u1E92': 'Z',
    '\u1E94': 'Z',
    '\u01B5': 'Z',
    '\u0224': 'Z',
    '\u2C7F': 'Z',
    '\u2C6B': 'Z',
    '\uA762': 'Z',
    '\u24D0': 'a',
    '\uFF41': 'a',
    '\u1E9A': 'a',
    '\u00E0': 'a',
    '\u00E1': 'a',
    '\u00E2': 'a',
    '\u1EA7': 'a',
    '\u1EA5': 'a',
    '\u1EAB': 'a',
    '\u1EA9': 'a',
    '\u00E3': 'a',
    '\u0101': 'a',
    '\u0103': 'a',
    '\u1EB1': 'a',
    '\u1EAF': 'a',
    '\u1EB5': 'a',
    '\u1EB3': 'a',
    '\u0227': 'a',
    '\u01E1': 'a',
    '\u00E4': 'a',
    '\u01DF': 'a',
    '\u1EA3': 'a',
    '\u00E5': 'a',
    '\u01FB': 'a',
    '\u01CE': 'a',
    '\u0201': 'a',
    '\u0203': 'a',
    '\u1EA1': 'a',
    '\u1EAD': 'a',
    '\u1EB7': 'a',
    '\u1E01': 'a',
    '\u0105': 'a',
    '\u2C65': 'a',
    '\u0250': 'a',
    '\uA733': 'aa',
    '\u00E6': 'ae',
    '\u01FD': 'ae',
    '\u01E3': 'ae',
    '\uA735': 'ao',
    '\uA737': 'au',
    '\uA739': 'av',
    '\uA73B': 'av',
    '\uA73D': 'ay',
    '\u24D1': 'b',
    '\uFF42': 'b',
    '\u1E03': 'b',
    '\u1E05': 'b',
    '\u1E07': 'b',
    '\u0180': 'b',
    '\u0183': 'b',
    '\u0253': 'b',
    '\u24D2': 'c',
    '\uFF43': 'c',
    '\u0107': 'c',
    '\u0109': 'c',
    '\u010B': 'c',
    '\u010D': 'c',
    '\u00E7': 'c',
    '\u1E09': 'c',
    '\u0188': 'c',
    '\u023C': 'c',
    '\uA73F': 'c',
    '\u2184': 'c',
    '\u24D3': 'd',
    '\uFF44': 'd',
    '\u1E0B': 'd',
    '\u010F': 'd',
    '\u1E0D': 'd',
    '\u1E11': 'd',
    '\u1E13': 'd',
    '\u1E0F': 'd',
    '\u0111': 'd',
    '\u018C': 'd',
    '\u0256': 'd',
    '\u0257': 'd',
    '\uA77A': 'd',
    '\u01F3': 'dz',
    '\u01C6': 'dz',
    '\u24D4': 'e',
    '\uFF45': 'e',
    '\u00E8': 'e',
    '\u00E9': 'e',
    '\u00EA': 'e',
    '\u1EC1': 'e',
    '\u1EBF': 'e',
    '\u1EC5': 'e',
    '\u1EC3': 'e',
    '\u1EBD': 'e',
    '\u0113': 'e',
    '\u1E15': 'e',
    '\u1E17': 'e',
    '\u0115': 'e',
    '\u0117': 'e',
    '\u00EB': 'e',
    '\u1EBB': 'e',
    '\u011B': 'e',
    '\u0205': 'e',
    '\u0207': 'e',
    '\u1EB9': 'e',
    '\u1EC7': 'e',
    '\u0229': 'e',
    '\u1E1D': 'e',
    '\u0119': 'e',
    '\u1E19': 'e',
    '\u1E1B': 'e',
    '\u0247': 'e',
    '\u025B': 'e',
    '\u01DD': 'e',
    '\u24D5': 'f',
    '\uFF46': 'f',
    '\u1E1F': 'f',
    '\u0192': 'f',
    '\uA77C': 'f',
    '\u24D6': 'g',
    '\uFF47': 'g',
    '\u01F5': 'g',
    '\u011D': 'g',
    '\u1E21': 'g',
    '\u011F': 'g',
    '\u0121': 'g',
    '\u01E7': 'g',
    '\u0123': 'g',
    '\u01E5': 'g',
    '\u0260': 'g',
    '\uA7A1': 'g',
    '\u1D79': 'g',
    '\uA77F': 'g',
    '\u24D7': 'h',
    '\uFF48': 'h',
    '\u0125': 'h',
    '\u1E23': 'h',
    '\u1E27': 'h',
    '\u021F': 'h',
    '\u1E25': 'h',
    '\u1E29': 'h',
    '\u1E2B': 'h',
    '\u1E96': 'h',
    '\u0127': 'h',
    '\u2C68': 'h',
    '\u2C76': 'h',
    '\u0265': 'h',
    '\u0195': 'hv',
    '\u24D8': 'i',
    '\uFF49': 'i',
    '\u00EC': 'i',
    '\u00ED': 'i',
    '\u00EE': 'i',
    '\u0129': 'i',
    '\u012B': 'i',
    '\u012D': 'i',
    '\u00EF': 'i',
    '\u1E2F': 'i',
    '\u1EC9': 'i',
    '\u01D0': 'i',
    '\u0209': 'i',
    '\u020B': 'i',
    '\u1ECB': 'i',
    '\u012F': 'i',
    '\u1E2D': 'i',
    '\u0268': 'i',
    '\u0131': 'i',
    '\u24D9': 'j',
    '\uFF4A': 'j',
    '\u0135': 'j',
    '\u01F0': 'j',
    '\u0249': 'j',
    '\u24DA': 'k',
    '\uFF4B': 'k',
    '\u1E31': 'k',
    '\u01E9': 'k',
    '\u1E33': 'k',
    '\u0137': 'k',
    '\u1E35': 'k',
    '\u0199': 'k',
    '\u2C6A': 'k',
    '\uA741': 'k',
    '\uA743': 'k',
    '\uA745': 'k',
    '\uA7A3': 'k',
    '\u24DB': 'l',
    '\uFF4C': 'l',
    '\u0140': 'l',
    '\u013A': 'l',
    '\u013E': 'l',
    '\u1E37': 'l',
    '\u1E39': 'l',
    '\u013C': 'l',
    '\u1E3D': 'l',
    '\u1E3B': 'l',
    '\u017F': 'l',
    '\u0142': 'l',
    '\u019A': 'l',
    '\u026B': 'l',
    '\u2C61': 'l',
    '\uA749': 'l',
    '\uA781': 'l',
    '\uA747': 'l',
    '\u01C9': 'lj',
    '\u24DC': 'm',
    '\uFF4D': 'm',
    '\u1E3F': 'm',
    '\u1E41': 'm',
    '\u1E43': 'm',
    '\u0271': 'm',
    '\u026F': 'm',
    '\u24DD': 'n',
    '\uFF4E': 'n',
    '\u01F9': 'n',
    '\u0144': 'n',
    '\u00F1': 'n',
    '\u1E45': 'n',
    '\u0148': 'n',
    '\u1E47': 'n',
    '\u0146': 'n',
    '\u1E4B': 'n',
    '\u1E49': 'n',
    '\u019E': 'n',
    '\u0272': 'n',
    '\u0149': 'n',
    '\uA791': 'n',
    '\uA7A5': 'n',
    '\u01CC': 'nj',
    '\u24DE': 'o',
    '\uFF4F': 'o',
    '\u00F2': 'o',
    '\u00F3': 'o',
    '\u00F4': 'o',
    '\u1ED3': 'o',
    '\u1ED1': 'o',
    '\u1ED7': 'o',
    '\u1ED5': 'o',
    '\u00F5': 'o',
    '\u1E4D': 'o',
    '\u022D': 'o',
    '\u1E4F': 'o',
    '\u014D': 'o',
    '\u1E51': 'o',
    '\u1E53': 'o',
    '\u014F': 'o',
    '\u022F': 'o',
    '\u0231': 'o',
    '\u00F6': 'o',
    '\u022B': 'o',
    '\u1ECF': 'o',
    '\u0151': 'o',
    '\u01D2': 'o',
    '\u020D': 'o',
    '\u020F': 'o',
    '\u01A1': 'o',
    '\u1EDD': 'o',
    '\u1EDB': 'o',
    '\u1EE1': 'o',
    '\u1EDF': 'o',
    '\u1EE3': 'o',
    '\u1ECD': 'o',
    '\u1ED9': 'o',
    '\u01EB': 'o',
    '\u01ED': 'o',
    '\u00F8': 'o',
    '\u01FF': 'o',
    '\u0254': 'o',
    '\uA74B': 'o',
    '\uA74D': 'o',
    '\u0275': 'o',
    '\u01A3': 'oi',
    '\u0223': 'ou',
    '\uA74F': 'oo',
    '\u24DF': 'p',
    '\uFF50': 'p',
    '\u1E55': 'p',
    '\u1E57': 'p',
    '\u01A5': 'p',
    '\u1D7D': 'p',
    '\uA751': 'p',
    '\uA753': 'p',
    '\uA755': 'p',
    '\u24E0': 'q',
    '\uFF51': 'q',
    '\u024B': 'q',
    '\uA757': 'q',
    '\uA759': 'q',
    '\u24E1': 'r',
    '\uFF52': 'r',
    '\u0155': 'r',
    '\u1E59': 'r',
    '\u0159': 'r',
    '\u0211': 'r',
    '\u0213': 'r',
    '\u1E5B': 'r',
    '\u1E5D': 'r',
    '\u0157': 'r',
    '\u1E5F': 'r',
    '\u024D': 'r',
    '\u027D': 'r',
    '\uA75B': 'r',
    '\uA7A7': 'r',
    '\uA783': 'r',
    '\u24E2': 's',
    '\uFF53': 's',
    '\u00DF': 's',
    '\u015B': 's',
    '\u1E65': 's',
    '\u015D': 's',
    '\u1E61': 's',
    '\u0161': 's',
    '\u1E67': 's',
    '\u1E63': 's',
    '\u1E69': 's',
    '\u0219': 's',
    '\u015F': 's',
    '\u023F': 's',
    '\uA7A9': 's',
    '\uA785': 's',
    '\u1E9B': 's',
    '\u24E3': 't',
    '\uFF54': 't',
    '\u1E6B': 't',
    '\u1E97': 't',
    '\u0165': 't',
    '\u1E6D': 't',
    '\u021B': 't',
    '\u0163': 't',
    '\u1E71': 't',
    '\u1E6F': 't',
    '\u0167': 't',
    '\u01AD': 't',
    '\u0288': 't',
    '\u2C66': 't',
    '\uA787': 't',
    '\uA729': 'tz',
    '\u24E4': 'u',
    '\uFF55': 'u',
    '\u00F9': 'u',
    '\u00FA': 'u',
    '\u00FB': 'u',
    '\u0169': 'u',
    '\u1E79': 'u',
    '\u016B': 'u',
    '\u1E7B': 'u',
    '\u016D': 'u',
    '\u00FC': 'u',
    '\u01DC': 'u',
    '\u01D8': 'u',
    '\u01D6': 'u',
    '\u01DA': 'u',
    '\u1EE7': 'u',
    '\u016F': 'u',
    '\u0171': 'u',
    '\u01D4': 'u',
    '\u0215': 'u',
    '\u0217': 'u',
    '\u01B0': 'u',
    '\u1EEB': 'u',
    '\u1EE9': 'u',
    '\u1EEF': 'u',
    '\u1EED': 'u',
    '\u1EF1': 'u',
    '\u1EE5': 'u',
    '\u1E73': 'u',
    '\u0173': 'u',
    '\u1E77': 'u',
    '\u1E75': 'u',
    '\u0289': 'u',
    '\u24E5': 'v',
    '\uFF56': 'v',
    '\u1E7D': 'v',
    '\u1E7F': 'v',
    '\u028B': 'v',
    '\uA75F': 'v',
    '\u028C': 'v',
    '\uA761': 'vy',
    '\u24E6': 'w',
    '\uFF57': 'w',
    '\u1E81': 'w',
    '\u1E83': 'w',
    '\u0175': 'w',
    '\u1E87': 'w',
    '\u1E85': 'w',
    '\u1E98': 'w',
    '\u1E89': 'w',
    '\u2C73': 'w',
    '\u24E7': 'x',
    '\uFF58': 'x',
    '\u1E8B': 'x',
    '\u1E8D': 'x',
    '\u24E8': 'y',
    '\uFF59': 'y',
    '\u1EF3': 'y',
    '\u00FD': 'y',
    '\u0177': 'y',
    '\u1EF9': 'y',
    '\u0233': 'y',
    '\u1E8F': 'y',
    '\u00FF': 'y',
    '\u1EF7': 'y',
    '\u1E99': 'y',
    '\u1EF5': 'y',
    '\u01B4': 'y',
    '\u024F': 'y',
    '\u1EFF': 'y',
    '\u24E9': 'z',
    '\uFF5A': 'z',
    '\u017A': 'z',
    '\u1E91': 'z',
    '\u017C': 'z',
    '\u017E': 'z',
    '\u1E93': 'z',
    '\u1E95': 'z',
    '\u01B6': 'z',
    '\u0225': 'z',
    '\u0240': 'z',
    '\u2C6C': 'z',
    '\uA763': 'z',
    '\u0386': '\u0391',
    '\u0388': '\u0395',
    '\u0389': '\u0397',
    '\u038A': '\u0399',
    '\u03AA': '\u0399',
    '\u038C': '\u039F',
    '\u038E': '\u03A5',
    '\u03AB': '\u03A5',
    '\u038F': '\u03A9',
    '\u03AC': '\u03B1',
    '\u03AD': '\u03B5',
    '\u03AE': '\u03B7',
    '\u03AF': '\u03B9',
    '\u03CA': '\u03B9',
    '\u0390': '\u03B9',
    '\u03CC': '\u03BF',
    '\u03CD': '\u03C5',
    '\u03CB': '\u03C5',
    '\u03B0': '\u03C5',
    '\u03C9': '\u03C9',
    '\u03C2': '\u03C3'
  };

  return diacritics;
});

S2.define('select2/data/base',[
  '../utils'
], function (Utils) {
  function BaseAdapter ($element, options) {
    BaseAdapter.__super__.constructor.call(this);
  }

  Utils.Extend(BaseAdapter, Utils.Observable);

  BaseAdapter.prototype.current = function (callback) {
    throw new Error('The `current` method must be defined in child classes.');
  };

  BaseAdapter.prototype.query = function (params, callback) {
    throw new Error('The `query` method must be defined in child classes.');
  };

  BaseAdapter.prototype.bind = function (container, $container) {
    // Can be implemented in subclasses
  };

  BaseAdapter.prototype.destroy = function () {
    // Can be implemented in subclasses
  };

  BaseAdapter.prototype.generateResultId = function (container, data) {
    var id = container.id + '-result-';

    id += Utils.generateChars(4);

    if (data.id != null) {
      id += '-' + data.id.toString();
    } else {
      id += '-' + Utils.generateChars(4);
    }
    return id;
  };

  return BaseAdapter;
});

S2.define('select2/data/select',[
  './base',
  '../utils',
  'jquery'
], function (BaseAdapter, Utils, $) {
  function SelectAdapter ($element, options) {
    this.$element = $element;
    this.options = options;

    SelectAdapter.__super__.constructor.call(this);
  }

  Utils.Extend(SelectAdapter, BaseAdapter);

  SelectAdapter.prototype.current = function (callback) {
    var data = [];
    var self = this;

    this.$element.find(':selected').each(function () {
      var $option = $(this);

      var option = self.item($option);

      data.push(option);
    });

    callback(data);
  };

  SelectAdapter.prototype.select = function (data) {
    var self = this;

    data.selected = true;

    // If data.element is a DOM node, use it instead
    if ($(data.element).is('option')) {
      data.element.selected = true;

      this.$element.trigger('change');

      return;
    }

    if (this.$element.prop('multiple')) {
      this.current(function (currentData) {
        var val = [];

        data = [data];
        data.push.apply(data, currentData);

        for (var d = 0; d < data.length; d++) {
          var id = data[d].id;

          if ($.inArray(id, val) === -1) {
            val.push(id);
          }
        }

        self.$element.val(val);
        self.$element.trigger('change');
      });
    } else {
      var val = data.id;

      this.$element.val(val);
      this.$element.trigger('change');
    }
  };

  SelectAdapter.prototype.unselect = function (data) {
    var self = this;

    if (!this.$element.prop('multiple')) {
      return;
    }

    data.selected = false;

    if ($(data.element).is('option')) {
      data.element.selected = false;

      this.$element.trigger('change');

      return;
    }

    this.current(function (currentData) {
      var val = [];

      for (var d = 0; d < currentData.length; d++) {
        var id = currentData[d].id;

        if (id !== data.id && $.inArray(id, val) === -1) {
          val.push(id);
        }
      }

      self.$element.val(val);

      self.$element.trigger('change');
    });
  };

  SelectAdapter.prototype.bind = function (container, $container) {
    var self = this;

    this.container = container;

    container.on('select', function (params) {
      self.select(params.data);
    });

    container.on('unselect', function (params) {
      self.unselect(params.data);
    });
  };

  SelectAdapter.prototype.destroy = function () {
    // Remove anything added to child elements
    this.$element.find('*').each(function () {
      // Remove any custom data set by Select2
      $.removeData(this, 'data');
    });
  };

  SelectAdapter.prototype.query = function (params, callback) {
    var data = [];
    var self = this;

    var $options = this.$element.children();

    $options.each(function () {
      var $option = $(this);

      if (!$option.is('option') && !$option.is('optgroup')) {
        return;
      }

      var option = self.item($option);

      var matches = self.matches(params, option);

      if (matches !== null) {
        data.push(matches);
      }
    });

    callback({
      results: data
    });
  };

  SelectAdapter.prototype.addOptions = function ($options) {
    Utils.appendMany(this.$element, $options);
  };

  SelectAdapter.prototype.option = function (data) {
    var option;

    if (data.children) {
      option = document.createElement('optgroup');
      option.label = data.text;
    } else {
      option = document.createElement('option');

      if (option.textContent !== undefined) {
        option.textContent = data.text;
      } else {
        option.innerText = data.text;
      }
    }

    if (data.id !== undefined) {
      option.value = data.id;
    }

    if (data.disabled) {
      option.disabled = true;
    }

    if (data.selected) {
      option.selected = true;
    }

    if (data.title) {
      option.title = data.title;
    }

    var $option = $(option);

    var normalizedData = this._normalizeItem(data);
    normalizedData.element = option;

    // Override the option's data with the combined data
    $.data(option, 'data', normalizedData);

    return $option;
  };

  SelectAdapter.prototype.item = function ($option) {
    var data = {};

    data = $.data($option[0], 'data');

    if (data != null) {
      return data;
    }

    if ($option.is('option')) {
      data = {
        id: $option.val(),
        text: $option.text(),
        disabled: $option.prop('disabled'),
        selected: $option.prop('selected'),
        title: $option.prop('title')
      };
    } else if ($option.is('optgroup')) {
      data = {
        text: $option.prop('label'),
        children: [],
        title: $option.prop('title')
      };

      var $children = $option.children('option');
      var children = [];

      for (var c = 0; c < $children.length; c++) {
        var $child = $($children[c]);

        var child = this.item($child);

        children.push(child);
      }

      data.children = children;
    }

    data = this._normalizeItem(data);
    data.element = $option[0];

    $.data($option[0], 'data', data);

    return data;
  };

  SelectAdapter.prototype._normalizeItem = function (item) {
    if (!$.isPlainObject(item)) {
      item = {
        id: item,
        text: item
      };
    }

    item = $.extend({}, {
      text: ''
    }, item);

    var defaults = {
      selected: false,
      disabled: false
    };

    if (item.id != null) {
      item.id = item.id.toString();
    }

    if (item.text != null) {
      item.text = item.text.toString();
    }

    if (item._resultId == null && item.id && this.container != null) {
      item._resultId = this.generateResultId(this.container, item);
    }

    return $.extend({}, defaults, item);
  };

  SelectAdapter.prototype.matches = function (params, data) {
    var matcher = this.options.get('matcher');

    return matcher(params, data);
  };

  return SelectAdapter;
});

S2.define('select2/data/array',[
  './select',
  '../utils',
  'jquery'
], function (SelectAdapter, Utils, $) {
  function ArrayAdapter ($element, options) {
    var data = options.get('data') || [];

    ArrayAdapter.__super__.constructor.call(this, $element, options);

    this.addOptions(this.convertToOptions(data));
  }

  Utils.Extend(ArrayAdapter, SelectAdapter);

  ArrayAdapter.prototype.select = function (data) {
    var $option = this.$element.find('option').filter(function (i, elm) {
      return elm.value == data.id.toString();
    });

    if ($option.length === 0) {
      $option = this.option(data);

      this.addOptions($option);
    }

    ArrayAdapter.__super__.select.call(this, data);
  };

  ArrayAdapter.prototype.convertToOptions = function (data) {
    var self = this;

    var $existing = this.$element.find('option');
    var existingIds = $existing.map(function () {
      return self.item($(this)).id;
    }).get();

    var $options = [];

    // Filter out all items except for the one passed in the argument
    function onlyItem (item) {
      return function () {
        return $(this).val() == item.id;
      };
    }

    for (var d = 0; d < data.length; d++) {
      var item = this._normalizeItem(data[d]);

      // Skip items which were pre-loaded, only merge the data
      if ($.inArray(item.id, existingIds) >= 0) {
        var $existingOption = $existing.filter(onlyItem(item));

        var existingData = this.item($existingOption);
        var newData = $.extend(true, {}, item, existingData);

        var $newOption = this.option(newData);

        $existingOption.replaceWith($newOption);

        continue;
      }

      var $option = this.option(item);

      if (item.children) {
        var $children = this.convertToOptions(item.children);

        Utils.appendMany($option, $children);
      }

      $options.push($option);
    }

    return $options;
  };

  return ArrayAdapter;
});

S2.define('select2/data/ajax',[
  './array',
  '../utils',
  'jquery'
], function (ArrayAdapter, Utils, $) {
  function AjaxAdapter ($element, options) {
    this.ajaxOptions = this._applyDefaults(options.get('ajax'));

    if (this.ajaxOptions.processResults != null) {
      this.processResults = this.ajaxOptions.processResults;
    }

    AjaxAdapter.__super__.constructor.call(this, $element, options);
  }

  Utils.Extend(AjaxAdapter, ArrayAdapter);

  AjaxAdapter.prototype._applyDefaults = function (options) {
    var defaults = {
      data: function (params) {
        return $.extend({}, params, {
          q: params.term
        });
      },
      transport: function (params, success, failure) {
        var $request = $.ajax(params);

        $request.then(success);
        $request.fail(failure);

        return $request;
      }
    };

    return $.extend({}, defaults, options, true);
  };

  AjaxAdapter.prototype.processResults = function (results) {
    return results;
  };

  AjaxAdapter.prototype.query = function (params, callback) {
    var matches = [];
    var self = this;

    if (this._request != null) {
      // JSONP requests cannot always be aborted
      if ($.isFunction(this._request.abort)) {
        this._request.abort();
      }

      this._request = null;
    }

    var options = $.extend({
      type: 'GET'
    }, this.ajaxOptions);

    if (typeof options.url === 'function') {
      options.url = options.url.call(this.$element, params);
    }

    if (typeof options.data === 'function') {
      options.data = options.data.call(this.$element, params);
    }

    function request () {
      var $request = options.transport(options, function (data) {
        var results = self.processResults(data, params);

        if (self.options.get('debug') && window.console && console.error) {
          // Check to make sure that the response included a `results` key.
          if (!results || !results.results || !$.isArray(results.results)) {
            console.error(
              'Select2: The AJAX results did not return an array in the ' +
              '`results` key of the response.'
            );
          }
        }

        callback(results);
      }, function () {
        // Attempt to detect if a request was aborted
        // Only works if the transport exposes a status property
        if ($request.status && $request.status === '0') {
          return;
        }

        self.trigger('results:message', {
          message: 'errorLoading'
        });
      });

      self._request = $request;
    }

    if (this.ajaxOptions.delay && params.term != null) {
      if (this._queryTimeout) {
        window.clearTimeout(this._queryTimeout);
      }

      this._queryTimeout = window.setTimeout(request, this.ajaxOptions.delay);
    } else {
      request();
    }
  };

  return AjaxAdapter;
});

S2.define('select2/data/tags',[
  'jquery'
], function ($) {
  function Tags (decorated, $element, options) {
    var tags = options.get('tags');

    var createTag = options.get('createTag');

    if (createTag !== undefined) {
      this.createTag = createTag;
    }

    var insertTag = options.get('insertTag');

    if (insertTag !== undefined) {
        this.insertTag = insertTag;
    }

    decorated.call(this, $element, options);

    if ($.isArray(tags)) {
      for (var t = 0; t < tags.length; t++) {
        var tag = tags[t];
        var item = this._normalizeItem(tag);

        var $option = this.option(item);

        this.$element.append($option);
      }
    }
  }

  Tags.prototype.query = function (decorated, params, callback) {
    var self = this;

    this._removeOldTags();

    if (params.term == null || params.page != null) {
      decorated.call(this, params, callback);
      return;
    }

    function wrapper (obj, child) {
      var data = obj.results;

      for (var i = 0; i < data.length; i++) {
        var option = data[i];

        var checkChildren = (
          option.children != null &&
          !wrapper({
            results: option.children
          }, true)
        );

        var optionText = (option.text || '').toUpperCase();
        var paramsTerm = (params.term || '').toUpperCase();

        var checkText = optionText === paramsTerm;

        if (checkText || checkChildren) {
          if (child) {
            return false;
          }

          obj.data = data;
          callback(obj);

          return;
        }
      }

      if (child) {
        return true;
      }

      var tag = self.createTag(params);

      if (tag != null) {
        var $option = self.option(tag);
        $option.attr('data-select2-tag', true);

        self.addOptions([$option]);

        self.insertTag(data, tag);
      }

      obj.results = data;

      callback(obj);
    }

    decorated.call(this, params, wrapper);
  };

  Tags.prototype.createTag = function (decorated, params) {
    var term = $.trim(params.term);

    if (term === '') {
      return null;
    }

    return {
      id: term,
      text: term
    };
  };

  Tags.prototype.insertTag = function (_, data, tag) {
    data.unshift(tag);
  };

  Tags.prototype._removeOldTags = function (_) {
    var tag = this._lastTag;

    var $options = this.$element.find('option[data-select2-tag]');

    $options.each(function () {
      if (this.selected) {
        return;
      }

      $(this).remove();
    });
  };

  return Tags;
});

S2.define('select2/data/tokenizer',[
  'jquery'
], function ($) {
  function Tokenizer (decorated, $element, options) {
    var tokenizer = options.get('tokenizer');

    if (tokenizer !== undefined) {
      this.tokenizer = tokenizer;
    }

    decorated.call(this, $element, options);
  }

  Tokenizer.prototype.bind = function (decorated, container, $container) {
    decorated.call(this, container, $container);

    this.$search =  container.dropdown.$search || container.selection.$search ||
      $container.find('.select2-search__field');
  };

  Tokenizer.prototype.query = function (decorated, params, callback) {
    var self = this;

    function createAndSelect (data) {
      // Normalize the data object so we can use it for checks
      var item = self._normalizeItem(data);

      // Check if the data object already exists as a tag
      // Select it if it doesn't
      var $existingOptions = self.$element.find('option').filter(function () {
        return $(this).val() === item.id;
      });

      // If an existing option wasn't found for it, create the option
      if (!$existingOptions.length) {
        var $option = self.option(item);
        $option.attr('data-select2-tag', true);

        self._removeOldTags();
        self.addOptions([$option]);
      }

      // Select the item, now that we know there is an option for it
      select(item);
    }

    function select (data) {
      self.trigger('select', {
        data: data
      });
    }

    params.term = params.term || '';

    var tokenData = this.tokenizer(params, this.options, createAndSelect);

    if (tokenData.term !== params.term) {
      // Replace the search term if we have the search box
      if (this.$search.length) {
        this.$search.val(tokenData.term);
        this.$search.focus();
      }

      params.term = tokenData.term;
    }

    decorated.call(this, params, callback);
  };

  Tokenizer.prototype.tokenizer = function (_, params, options, callback) {
    var separators = options.get('tokenSeparators') || [];
    var term = params.term;
    var i = 0;

    var createTag = this.createTag || function (params) {
      return {
        id: params.term,
        text: params.term
      };
    };

    while (i < term.length) {
      var termChar = term[i];

      if ($.inArray(termChar, separators) === -1) {
        i++;

        continue;
      }

      var part = term.substr(0, i);
      var partParams = $.extend({}, params, {
        term: part
      });

      var data = createTag(partParams);

      if (data == null) {
        i++;
        continue;
      }

      callback(data);

      // Reset the term to not include the tokenized portion
      term = term.substr(i + 1) || '';
      i = 0;
    }

    return {
      term: term
    };
  };

  return Tokenizer;
});

S2.define('select2/data/minimumInputLength',[

], function () {
  function MinimumInputLength (decorated, $e, options) {
    this.minimumInputLength = options.get('minimumInputLength');

    decorated.call(this, $e, options);
  }

  MinimumInputLength.prototype.query = function (decorated, params, callback) {
    params.term = params.term || '';

    if (params.term.length < this.minimumInputLength) {
      this.trigger('results:message', {
        message: 'inputTooShort',
        args: {
          minimum: this.minimumInputLength,
          input: params.term,
          params: params
        }
      });

      return;
    }

    decorated.call(this, params, callback);
  };

  return MinimumInputLength;
});

S2.define('select2/data/maximumInputLength',[

], function () {
  function MaximumInputLength (decorated, $e, options) {
    this.maximumInputLength = options.get('maximumInputLength');

    decorated.call(this, $e, options);
  }

  MaximumInputLength.prototype.query = function (decorated, params, callback) {
    params.term = params.term || '';

    if (this.maximumInputLength > 0 &&
        params.term.length > this.maximumInputLength) {
      this.trigger('results:message', {
        message: 'inputTooLong',
        args: {
          maximum: this.maximumInputLength,
          input: params.term,
          params: params
        }
      });

      return;
    }

    decorated.call(this, params, callback);
  };

  return MaximumInputLength;
});

S2.define('select2/data/maximumSelectionLength',[

], function (){
  function MaximumSelectionLength (decorated, $e, options) {
    this.maximumSelectionLength = options.get('maximumSelectionLength');

    decorated.call(this, $e, options);
  }

  MaximumSelectionLength.prototype.query =
    function (decorated, params, callback) {
      var self = this;

      this.current(function (currentData) {
        var count = currentData != null ? currentData.length : 0;
        if (self.maximumSelectionLength > 0 &&
          count >= self.maximumSelectionLength) {
          self.trigger('results:message', {
            message: 'maximumSelected',
            args: {
              maximum: self.maximumSelectionLength
            }
          });
          return;
        }
        decorated.call(self, params, callback);
      });
  };

  return MaximumSelectionLength;
});

S2.define('select2/dropdown',[
  'jquery',
  './utils'
], function ($, Utils) {
  function Dropdown ($element, options) {
    this.$element = $element;
    this.options = options;

    Dropdown.__super__.constructor.call(this);
  }

  Utils.Extend(Dropdown, Utils.Observable);

  Dropdown.prototype.render = function () {
    var $dropdown = $(
      '<span class="select2-dropdown">' +
        '<span class="select2-results"></span>' +
      '</span>'
    );

    $dropdown.attr('dir', this.options.get('dir'));

    this.$dropdown = $dropdown;

    return $dropdown;
  };

  Dropdown.prototype.bind = function () {
    // Should be implemented in subclasses
  };

  Dropdown.prototype.position = function ($dropdown, $container) {
    // Should be implmented in subclasses
  };

  Dropdown.prototype.destroy = function () {
    // Remove the dropdown from the DOM
    this.$dropdown.remove();
  };

  return Dropdown;
});

S2.define('select2/dropdown/search',[
  'jquery',
  '../utils'
], function ($, Utils) {
  function Search () { }

  Search.prototype.render = function (decorated) {
    var $rendered = decorated.call(this);

    var $search = $(
      '<span class="select2-search select2-search--dropdown">' +
        '<input class="select2-search__field" type="search" tabindex="-1"' +
        ' autocomplete="off" autocorrect="off" autocapitalize="off"' +
        ' spellcheck="false" role="textbox" />' +
      '</span>'
    );

    this.$searchContainer = $search;
    this.$search = $search.find('input');

    $rendered.prepend($search);

    return $rendered;
  };

  Search.prototype.bind = function (decorated, container, $container) {
    var self = this;

    decorated.call(this, container, $container);

    this.$search.on('keydown', function (evt) {
      self.trigger('keypress', evt);

      self._keyUpPrevented = evt.isDefaultPrevented();
    });

    // Workaround for browsers which do not support the `input` event
    // This will prevent double-triggering of events for browsers which support
    // both the `keyup` and `input` events.
    this.$search.on('input', function (evt) {
      // Unbind the duplicated `keyup` event
      $(this).off('keyup');
    });

    this.$search.on('keyup input', function (evt) {
      self.handleSearch(evt);
    });

    container.on('open', function () {
      self.$search.attr('tabindex', 0);

      self.$search.focus();

      window.setTimeout(function () {
        self.$search.focus();
      }, 0);
    });

    container.on('close', function () {
      self.$search.attr('tabindex', -1);

      self.$search.val('');
    });

    container.on('focus', function () {
      if (!container.isOpen()) {
        self.$search.focus();
      }
    });

    container.on('results:all', function (params) {
      if (params.query.term == null || params.query.term === '') {
        var showSearch = self.showSearch(params);

        if (showSearch) {
          self.$searchContainer.removeClass('select2-search--hide');
        } else {
          self.$searchContainer.addClass('select2-search--hide');
        }
      }
    });
  };

  Search.prototype.handleSearch = function (evt) {
    if (!this._keyUpPrevented) {
      var input = this.$search.val();

      this.trigger('query', {
        term: input
      });
    }

    this._keyUpPrevented = false;
  };

  Search.prototype.showSearch = function (_, params) {
    return true;
  };

  return Search;
});

S2.define('select2/dropdown/hidePlaceholder',[

], function () {
  function HidePlaceholder (decorated, $element, options, dataAdapter) {
    this.placeholder = this.normalizePlaceholder(options.get('placeholder'));

    decorated.call(this, $element, options, dataAdapter);
  }

  HidePlaceholder.prototype.append = function (decorated, data) {
    data.results = this.removePlaceholder(data.results);

    decorated.call(this, data);
  };

  HidePlaceholder.prototype.normalizePlaceholder = function (_, placeholder) {
    if (typeof placeholder === 'string') {
      placeholder = {
        id: '',
        text: placeholder
      };
    }

    return placeholder;
  };

  HidePlaceholder.prototype.removePlaceholder = function (_, data) {
    var modifiedData = data.slice(0);

    for (var d = data.length - 1; d >= 0; d--) {
      var item = data[d];

      if (this.placeholder.id === item.id) {
        modifiedData.splice(d, 1);
      }
    }

    return modifiedData;
  };

  return HidePlaceholder;
});

S2.define('select2/dropdown/infiniteScroll',[
  'jquery'
], function ($) {
  function InfiniteScroll (decorated, $element, options, dataAdapter) {
    this.lastParams = {};

    decorated.call(this, $element, options, dataAdapter);

    this.$loadingMore = this.createLoadingMore();
    this.loading = false;
  }

  InfiniteScroll.prototype.append = function (decorated, data) {
    this.$loadingMore.remove();
    this.loading = false;

    decorated.call(this, data);

    if (this.showLoadingMore(data)) {
      this.$results.append(this.$loadingMore);
    }
  };

  InfiniteScroll.prototype.bind = function (decorated, container, $container) {
    var self = this;

    decorated.call(this, container, $container);

    container.on('query', function (params) {
      self.lastParams = params;
      self.loading = true;
    });

    container.on('query:append', function (params) {
      self.lastParams = params;
      self.loading = true;
    });

    this.$results.on('scroll', function () {
      var isLoadMoreVisible = $.contains(
        document.documentElement,
        self.$loadingMore[0]
      );

      if (self.loading || !isLoadMoreVisible) {
        return;
      }

      var currentOffset = self.$results.offset().top +
        self.$results.outerHeight(false);
      var loadingMoreOffset = self.$loadingMore.offset().top +
        self.$loadingMore.outerHeight(false);

      if (currentOffset + 50 >= loadingMoreOffset) {
        self.loadMore();
      }
    });
  };

  InfiniteScroll.prototype.loadMore = function () {
    this.loading = true;

    var params = $.extend({}, {page: 1}, this.lastParams);

    params.page++;

    this.trigger('query:append', params);
  };

  InfiniteScroll.prototype.showLoadingMore = function (_, data) {
    return data.pagination && data.pagination.more;
  };

  InfiniteScroll.prototype.createLoadingMore = function () {
    var $option = $(
      '<li ' +
      'class="select2-results__option select2-results__option--load-more"' +
      'role="treeitem" aria-disabled="true"></li>'
    );

    var message = this.options.get('translations').get('loadingMore');

    $option.html(message(this.lastParams));

    return $option;
  };

  return InfiniteScroll;
});

S2.define('select2/dropdown/attachBody',[
  'jquery',
  '../utils'
], function ($, Utils) {
  function AttachBody (decorated, $element, options) {
    this.$dropdownParent = options.get('dropdownParent') || $(document.body);

    decorated.call(this, $element, options);
  }

  AttachBody.prototype.bind = function (decorated, container, $container) {
    var self = this;

    var setupResultsEvents = false;

    decorated.call(this, container, $container);

    container.on('open', function () {
      self._showDropdown();
      self._attachPositioningHandler(container);

      if (!setupResultsEvents) {
        setupResultsEvents = true;

        container.on('results:all', function () {
          self._positionDropdown();
          self._resizeDropdown();
        });

        container.on('results:append', function () {
          self._positionDropdown();
          self._resizeDropdown();
        });
      }
    });

    container.on('close', function () {
      self._hideDropdown();
      self._detachPositioningHandler(container);
    });

    this.$dropdownContainer.on('mousedown', function (evt) {
      evt.stopPropagation();
    });
  };

  AttachBody.prototype.destroy = function (decorated) {
    decorated.call(this);

    this.$dropdownContainer.remove();
  };

  AttachBody.prototype.position = function (decorated, $dropdown, $container) {
    // Clone all of the container classes
    $dropdown.attr('class', $container.attr('class'));

    $dropdown.removeClass('select2');
    $dropdown.addClass('select2-container--open');

    $dropdown.css({
      position: 'absolute',
      top: -999999
    });

    this.$container = $container;
  };

  AttachBody.prototype.render = function (decorated) {
    var $container = $('<span></span>');

    var $dropdown = decorated.call(this);
    $container.append($dropdown);

    this.$dropdownContainer = $container;

    return $container;
  };

  AttachBody.prototype._hideDropdown = function (decorated) {
    this.$dropdownContainer.detach();
  };

  AttachBody.prototype._attachPositioningHandler =
      function (decorated, container) {
    var self = this;

    var scrollEvent = 'scroll.select2.' + container.id;
    var resizeEvent = 'resize.select2.' + container.id;
    var orientationEvent = 'orientationchange.select2.' + container.id;

    var $watchers = this.$container.parents().filter(Utils.hasScroll);
    $watchers.each(function () {
      $(this).data('select2-scroll-position', {
        x: $(this).scrollLeft(),
        y: $(this).scrollTop()
      });
    });

    $watchers.on(scrollEvent, function (ev) {
      var position = $(this).data('select2-scroll-position');
      $(this).scrollTop(position.y);
    });

    $(window).on(scrollEvent + ' ' + resizeEvent + ' ' + orientationEvent,
      function (e) {
      self._positionDropdown();
      self._resizeDropdown();
    });
  };

  AttachBody.prototype._detachPositioningHandler =
      function (decorated, container) {
    var scrollEvent = 'scroll.select2.' + container.id;
    var resizeEvent = 'resize.select2.' + container.id;
    var orientationEvent = 'orientationchange.select2.' + container.id;

    var $watchers = this.$container.parents().filter(Utils.hasScroll);
    $watchers.off(scrollEvent);

    $(window).off(scrollEvent + ' ' + resizeEvent + ' ' + orientationEvent);
  };

  AttachBody.prototype._positionDropdown = function () {
    var $window = $(window);

    var isCurrentlyAbove = this.$dropdown.hasClass('select2-dropdown--above');
    var isCurrentlyBelow = this.$dropdown.hasClass('select2-dropdown--below');

    var newDirection = null;

    var offset = this.$container.offset();

    offset.bottom = offset.top + this.$container.outerHeight(false);

    var container = {
      height: this.$container.outerHeight(false)
    };

    container.top = offset.top;
    container.bottom = offset.top + container.height;

    var dropdown = {
      height: this.$dropdown.outerHeight(false)
    };

    var viewport = {
      top: $window.scrollTop(),
      bottom: $window.scrollTop() + $window.height()
    };

    var enoughRoomAbove = viewport.top < (offset.top - dropdown.height);
    var enoughRoomBelow = viewport.bottom > (offset.bottom + dropdown.height);

    var css = {
      left: offset.left,
      top: container.bottom
    };

    // Determine what the parent element is to use for calciulating the offset
    var $offsetParent = this.$dropdownParent;

    // For statically positoned elements, we need to get the element
    // that is determining the offset
    if ($offsetParent.css('position') === 'static') {
      $offsetParent = $offsetParent.offsetParent();
    }

    var parentOffset = $offsetParent.offset();

    css.top -= parentOffset.top;
    css.left -= parentOffset.left;

    if (!isCurrentlyAbove && !isCurrentlyBelow) {
      newDirection = 'below';
    }

    if (!enoughRoomBelow && enoughRoomAbove && !isCurrentlyAbove) {
      newDirection = 'above';
    } else if (!enoughRoomAbove && enoughRoomBelow && isCurrentlyAbove) {
      newDirection = 'below';
    }

    if (newDirection == 'above' ||
      (isCurrentlyAbove && newDirection !== 'below')) {
      css.top = container.top - parentOffset.top - dropdown.height;
    }

    if (newDirection != null) {
      this.$dropdown
        .removeClass('select2-dropdown--below select2-dropdown--above')
        .addClass('select2-dropdown--' + newDirection);
      this.$container
        .removeClass('select2-container--below select2-container--above')
        .addClass('select2-container--' + newDirection);
    }

    this.$dropdownContainer.css(css);
  };

  AttachBody.prototype._resizeDropdown = function () {
    var css = {
      width: this.$container.outerWidth(false) + 'px'
    };

    if (this.options.get('dropdownAutoWidth')) {
      css.minWidth = css.width;
      css.position = 'relative';
      css.width = 'auto';
    }

    this.$dropdown.css(css);
  };

  AttachBody.prototype._showDropdown = function (decorated) {
    this.$dropdownContainer.appendTo(this.$dropdownParent);

    this._positionDropdown();
    this._resizeDropdown();
  };

  return AttachBody;
});

S2.define('select2/dropdown/minimumResultsForSearch',[

], function () {
  function countResults (data) {
    var count = 0;

    for (var d = 0; d < data.length; d++) {
      var item = data[d];

      if (item.children) {
        count += countResults(item.children);
      } else {
        count++;
      }
    }

    return count;
  }

  function MinimumResultsForSearch (decorated, $element, options, dataAdapter) {
    this.minimumResultsForSearch = options.get('minimumResultsForSearch');

    if (this.minimumResultsForSearch < 0) {
      this.minimumResultsForSearch = Infinity;
    }

    decorated.call(this, $element, options, dataAdapter);
  }

  MinimumResultsForSearch.prototype.showSearch = function (decorated, params) {
    if (countResults(params.data.results) < this.minimumResultsForSearch) {
      return false;
    }

    return decorated.call(this, params);
  };

  return MinimumResultsForSearch;
});

S2.define('select2/dropdown/selectOnClose',[

], function () {
  function SelectOnClose () { }

  SelectOnClose.prototype.bind = function (decorated, container, $container) {
    var self = this;

    decorated.call(this, container, $container);

    container.on('close', function (params) {
      self._handleSelectOnClose(params);
    });
  };

  SelectOnClose.prototype._handleSelectOnClose = function (_, params) {
    if (params && params.originalSelect2Event != null) {
      var event = params.originalSelect2Event;

      // Don't select an item if the close event was triggered from a select or
      // unselect event
      if (event._type === 'select' || event._type === 'unselect') {
        return;
      }
    }

    var $highlightedResults = this.getHighlightedResults();

    // Only select highlighted results
    if ($highlightedResults.length < 1) {
      return;
    }

    var data = $highlightedResults.data('data');

    // Don't re-select already selected resulte
    if (
      (data.element != null && data.element.selected) ||
      (data.element == null && data.selected)
    ) {
      return;
    }

    this.trigger('select', {
        data: data
    });
  };

  return SelectOnClose;
});

S2.define('select2/dropdown/closeOnSelect',[

], function () {
  function CloseOnSelect () { }

  CloseOnSelect.prototype.bind = function (decorated, container, $container) {
    var self = this;

    decorated.call(this, container, $container);

    container.on('select', function (evt) {
      self._selectTriggered(evt);
    });

    container.on('unselect', function (evt) {
      self._selectTriggered(evt);
    });
  };

  CloseOnSelect.prototype._selectTriggered = function (_, evt) {
    var originalEvent = evt.originalEvent;

    // Don't close if the control key is being held
    if (originalEvent && originalEvent.ctrlKey) {
      return;
    }

    this.trigger('close', {
      originalEvent: originalEvent,
      originalSelect2Event: evt
    });
  };

  return CloseOnSelect;
});

S2.define('select2/i18n/en',[],function () {
  // English
  return {
    errorLoading: function () {
      return 'The results could not be loaded.';
    },
    inputTooLong: function (args) {
      var overChars = args.input.length - args.maximum;

      var message = 'Please delete ' + overChars + ' character';

      if (overChars != 1) {
        message += 's';
      }

      return message;
    },
    inputTooShort: function (args) {
      var remainingChars = args.minimum - args.input.length;

      var message = 'Please enter ' + remainingChars + ' or more characters';

      return message;
    },
    loadingMore: function () {
      return 'Loading more results…';
    },
    maximumSelected: function (args) {
      var message = 'You can only select ' + args.maximum + ' item';

      if (args.maximum != 1) {
        message += 's';
      }

      return message;
    },
    noResults: function () {
      return 'No results found';
    },
    searching: function () {
      return 'Searching…';
    }
  };
});

S2.define('select2/defaults',[
  'jquery',
  'require',

  './results',

  './selection/single',
  './selection/multiple',
  './selection/placeholder',
  './selection/allowClear',
  './selection/search',
  './selection/eventRelay',

  './utils',
  './translation',
  './diacritics',

  './data/select',
  './data/array',
  './data/ajax',
  './data/tags',
  './data/tokenizer',
  './data/minimumInputLength',
  './data/maximumInputLength',
  './data/maximumSelectionLength',

  './dropdown',
  './dropdown/search',
  './dropdown/hidePlaceholder',
  './dropdown/infiniteScroll',
  './dropdown/attachBody',
  './dropdown/minimumResultsForSearch',
  './dropdown/selectOnClose',
  './dropdown/closeOnSelect',

  './i18n/en'
], function ($, require,

             ResultsList,

             SingleSelection, MultipleSelection, Placeholder, AllowClear,
             SelectionSearch, EventRelay,

             Utils, Translation, DIACRITICS,

             SelectData, ArrayData, AjaxData, Tags, Tokenizer,
             MinimumInputLength, MaximumInputLength, MaximumSelectionLength,

             Dropdown, DropdownSearch, HidePlaceholder, InfiniteScroll,
             AttachBody, MinimumResultsForSearch, SelectOnClose, CloseOnSelect,

             EnglishTranslation) {
  function Defaults () {
    this.reset();
  }

  Defaults.prototype.apply = function (options) {
    options = $.extend(true, {}, this.defaults, options);

    if (options.dataAdapter == null) {
      if (options.ajax != null) {
        options.dataAdapter = AjaxData;
      } else if (options.data != null) {
        options.dataAdapter = ArrayData;
      } else {
        options.dataAdapter = SelectData;
      }

      if (options.minimumInputLength > 0) {
        options.dataAdapter = Utils.Decorate(
          options.dataAdapter,
          MinimumInputLength
        );
      }

      if (options.maximumInputLength > 0) {
        options.dataAdapter = Utils.Decorate(
          options.dataAdapter,
          MaximumInputLength
        );
      }

      if (options.maximumSelectionLength > 0) {
        options.dataAdapter = Utils.Decorate(
          options.dataAdapter,
          MaximumSelectionLength
        );
      }

      if (options.tags) {
        options.dataAdapter = Utils.Decorate(options.dataAdapter, Tags);
      }

      if (options.tokenSeparators != null || options.tokenizer != null) {
        options.dataAdapter = Utils.Decorate(
          options.dataAdapter,
          Tokenizer
        );
      }

      if (options.query != null) {
        var Query = require(options.amdBase + 'compat/query');

        options.dataAdapter = Utils.Decorate(
          options.dataAdapter,
          Query
        );
      }

      if (options.initSelection != null) {
        var InitSelection = require(options.amdBase + 'compat/initSelection');

        options.dataAdapter = Utils.Decorate(
          options.dataAdapter,
          InitSelection
        );
      }
    }

    if (options.resultsAdapter == null) {
      options.resultsAdapter = ResultsList;

      if (options.ajax != null) {
        options.resultsAdapter = Utils.Decorate(
          options.resultsAdapter,
          InfiniteScroll
        );
      }

      if (options.placeholder != null) {
        options.resultsAdapter = Utils.Decorate(
          options.resultsAdapter,
          HidePlaceholder
        );
      }

      if (options.selectOnClose) {
        options.resultsAdapter = Utils.Decorate(
          options.resultsAdapter,
          SelectOnClose
        );
      }
    }

    if (options.dropdownAdapter == null) {
      if (options.multiple) {
        options.dropdownAdapter = Dropdown;
      } else {
        var SearchableDropdown = Utils.Decorate(Dropdown, DropdownSearch);

        options.dropdownAdapter = SearchableDropdown;
      }

      if (options.minimumResultsForSearch !== 0) {
        options.dropdownAdapter = Utils.Decorate(
          options.dropdownAdapter,
          MinimumResultsForSearch
        );
      }

      if (options.closeOnSelect) {
        options.dropdownAdapter = Utils.Decorate(
          options.dropdownAdapter,
          CloseOnSelect
        );
      }

      if (
        options.dropdownCssClass != null ||
        options.dropdownCss != null ||
        options.adaptDropdownCssClass != null
      ) {
        var DropdownCSS = require(options.amdBase + 'compat/dropdownCss');

        options.dropdownAdapter = Utils.Decorate(
          options.dropdownAdapter,
          DropdownCSS
        );
      }

      options.dropdownAdapter = Utils.Decorate(
        options.dropdownAdapter,
        AttachBody
      );
    }

    if (options.selectionAdapter == null) {
      if (options.multiple) {
        options.selectionAdapter = MultipleSelection;
      } else {
        options.selectionAdapter = SingleSelection;
      }

      // Add the placeholder mixin if a placeholder was specified
      if (options.placeholder != null) {
        options.selectionAdapter = Utils.Decorate(
          options.selectionAdapter,
          Placeholder
        );
      }

      if (options.allowClear) {
        options.selectionAdapter = Utils.Decorate(
          options.selectionAdapter,
          AllowClear
        );
      }

      if (options.multiple) {
        options.selectionAdapter = Utils.Decorate(
          options.selectionAdapter,
          SelectionSearch
        );
      }

      if (
        options.containerCssClass != null ||
        options.containerCss != null ||
        options.adaptContainerCssClass != null
      ) {
        var ContainerCSS = require(options.amdBase + 'compat/containerCss');

        options.selectionAdapter = Utils.Decorate(
          options.selectionAdapter,
          ContainerCSS
        );
      }

      options.selectionAdapter = Utils.Decorate(
        options.selectionAdapter,
        EventRelay
      );
    }

    if (typeof options.language === 'string') {
      // Check if the language is specified with a region
      if (options.language.indexOf('-') > 0) {
        // Extract the region information if it is included
        var languageParts = options.language.split('-');
        var baseLanguage = languageParts[0];

        options.language = [options.language, baseLanguage];
      } else {
        options.language = [options.language];
      }
    }

    if ($.isArray(options.language)) {
      var languages = new Translation();
      options.language.push('en');

      var languageNames = options.language;

      for (var l = 0; l < languageNames.length; l++) {
        var name = languageNames[l];
        var language = {};

        try {
          // Try to load it with the original name
          language = Translation.loadPath(name);
        } catch (e) {
          try {
            // If we couldn't load it, check if it wasn't the full path
            name = this.defaults.amdLanguageBase + name;
            language = Translation.loadPath(name);
          } catch (ex) {
            // The translation could not be loaded at all. Sometimes this is
            // because of a configuration problem, other times this can be
            // because of how Select2 helps load all possible translation files.
            if (options.debug && window.console && console.warn) {
              console.warn(
                'Select2: The language file for "' + name + '" could not be ' +
                'automatically loaded. A fallback will be used instead.'
              );
            }

            continue;
          }
        }

        languages.extend(language);
      }

      options.translations = languages;
    } else {
      var baseTranslation = Translation.loadPath(
        this.defaults.amdLanguageBase + 'en'
      );
      var customTranslation = new Translation(options.language);

      customTranslation.extend(baseTranslation);

      options.translations = customTranslation;
    }

    return options;
  };

  Defaults.prototype.reset = function () {
    function stripDiacritics (text) {
      // Used 'uni range + named function' from http://jsperf.com/diacritics/18
      function match(a) {
        return DIACRITICS[a] || a;
      }

      return text.replace(/[^\u0000-\u007E]/g, match);
    }

    function matcher (params, data) {
      // Always return the object if there is nothing to compare
      if ($.trim(params.term) === '') {
        return data;
      }

      // Do a recursive check for options with children
      if (data.children && data.children.length > 0) {
        // Clone the data object if there are children
        // This is required as we modify the object to remove any non-matches
        var match = $.extend(true, {}, data);

        // Check each child of the option
        for (var c = data.children.length - 1; c >= 0; c--) {
          var child = data.children[c];

          var matches = matcher(params, child);

          // If there wasn't a match, remove the object in the array
          if (matches == null) {
            match.children.splice(c, 1);
          }
        }

        // If any children matched, return the new object
        if (match.children.length > 0) {
          return match;
        }

        // If there were no matching children, check just the plain object
        return matcher(params, match);
      }

      var original = stripDiacritics(data.text).toUpperCase();
      var term = stripDiacritics(params.term).toUpperCase();

      // Check if the text contains the term
      if (original.indexOf(term) > -1) {
        return data;
      }

      // If it doesn't contain the term, don't return anything
      return null;
    }

    this.defaults = {
      amdBase: './',
      amdLanguageBase: './i18n/',
      closeOnSelect: true,
      debug: false,
      dropdownAutoWidth: false,
      escapeMarkup: Utils.escapeMarkup,
      language: EnglishTranslation,
      matcher: matcher,
      minimumInputLength: 0,
      maximumInputLength: 0,
      maximumSelectionLength: 0,
      minimumResultsForSearch: 0,
      selectOnClose: false,
      sorter: function (data) {
        return data;
      },
      templateResult: function (result) {
        return result.text;
      },
      templateSelection: function (selection) {
        return selection.text;
      },
      theme: 'default',
      width: 'resolve'
    };
  };

  Defaults.prototype.set = function (key, value) {
    var camelKey = $.camelCase(key);

    var data = {};
    data[camelKey] = value;

    var convertedData = Utils._convertData(data);

    $.extend(this.defaults, convertedData);
  };

  var defaults = new Defaults();

  return defaults;
});

S2.define('select2/options',[
  'require',
  'jquery',
  './defaults',
  './utils'
], function (require, $, Defaults, Utils) {
  function Options (options, $element) {
    this.options = options;

    if ($element != null) {
      this.fromElement($element);
    }

    this.options = Defaults.apply(this.options);

    if ($element && $element.is('input')) {
      var InputCompat = require(this.get('amdBase') + 'compat/inputData');

      this.options.dataAdapter = Utils.Decorate(
        this.options.dataAdapter,
        InputCompat
      );
    }
  }

  Options.prototype.fromElement = function ($e) {
    var excludedData = ['select2'];

    if (this.options.multiple == null) {
      this.options.multiple = $e.prop('multiple');
    }

    if (this.options.disabled == null) {
      this.options.disabled = $e.prop('disabled');
    }

    if (this.options.language == null) {
      if ($e.prop('lang')) {
        this.options.language = $e.prop('lang').toLowerCase();
      } else if ($e.closest('[lang]').prop('lang')) {
        this.options.language = $e.closest('[lang]').prop('lang');
      }
    }

    if (this.options.dir == null) {
      if ($e.prop('dir')) {
        this.options.dir = $e.prop('dir');
      } else if ($e.closest('[dir]').prop('dir')) {
        this.options.dir = $e.closest('[dir]').prop('dir');
      } else {
        this.options.dir = 'ltr';
      }
    }

    $e.prop('disabled', this.options.disabled);
    $e.prop('multiple', this.options.multiple);

    if ($e.data('select2Tags')) {
      if (this.options.debug && window.console && console.warn) {
        console.warn(
          'Select2: The `data-select2-tags` attribute has been changed to ' +
          'use the `data-data` and `data-tags="true"` attributes and will be ' +
          'removed in future versions of Select2.'
        );
      }

      $e.data('data', $e.data('select2Tags'));
      $e.data('tags', true);
    }

    if ($e.data('ajaxUrl')) {
      if (this.options.debug && window.console && console.warn) {
        console.warn(
          'Select2: The `data-ajax-url` attribute has been changed to ' +
          '`data-ajax--url` and support for the old attribute will be removed' +
          ' in future versions of Select2.'
        );
      }

      $e.attr('ajax--url', $e.data('ajaxUrl'));
      $e.data('ajax--url', $e.data('ajaxUrl'));
    }

    var dataset = {};

    // Prefer the element's `dataset` attribute if it exists
    // jQuery 1.x does not correctly handle data attributes with multiple dashes
    if ($.fn.jquery && $.fn.jquery.substr(0, 2) == '1.' && $e[0].dataset) {
      dataset = $.extend(true, {}, $e[0].dataset, $e.data());
    } else {
      dataset = $e.data();
    }

    var data = $.extend(true, {}, dataset);

    data = Utils._convertData(data);

    for (var key in data) {
      if ($.inArray(key, excludedData) > -1) {
        continue;
      }

      if ($.isPlainObject(this.options[key])) {
        $.extend(this.options[key], data[key]);
      } else {
        this.options[key] = data[key];
      }
    }

    return this;
  };

  Options.prototype.get = function (key) {
    return this.options[key];
  };

  Options.prototype.set = function (key, val) {
    this.options[key] = val;
  };

  return Options;
});

S2.define('select2/core',[
  'jquery',
  './options',
  './utils',
  './keys'
], function ($, Options, Utils, KEYS) {
  var Select2 = function ($element, options) {
    if ($element.data('select2') != null) {
      $element.data('select2').destroy();
    }

    this.$element = $element;

    this.id = this._generateId($element);

    options = options || {};

    this.options = new Options(options, $element);

    Select2.__super__.constructor.call(this);

    // Set up the tabindex

    var tabindex = $element.attr('tabindex') || 0;
    $element.data('old-tabindex', tabindex);
    $element.attr('tabindex', '-1');

    // Set up containers and adapters

    var DataAdapter = this.options.get('dataAdapter');
    this.dataAdapter = new DataAdapter($element, this.options);

    var $container = this.render();

    this._placeContainer($container);

    var SelectionAdapter = this.options.get('selectionAdapter');
    this.selection = new SelectionAdapter($element, this.options);
    this.$selection = this.selection.render();

    this.selection.position(this.$selection, $container);

    var DropdownAdapter = this.options.get('dropdownAdapter');
    this.dropdown = new DropdownAdapter($element, this.options);
    this.$dropdown = this.dropdown.render();

    this.dropdown.position(this.$dropdown, $container);

    var ResultsAdapter = this.options.get('resultsAdapter');
    this.results = new ResultsAdapter($element, this.options, this.dataAdapter);
    this.$results = this.results.render();

    this.results.position(this.$results, this.$dropdown);

    // Bind events

    var self = this;

    // Bind the container to all of the adapters
    this._bindAdapters();

    // Register any DOM event handlers
    this._registerDomEvents();

    // Register any internal event handlers
    this._registerDataEvents();
    this._registerSelectionEvents();
    this._registerDropdownEvents();
    this._registerResultsEvents();
    this._registerEvents();

    // Set the initial state
    this.dataAdapter.current(function (initialData) {
      self.trigger('selection:update', {
        data: initialData
      });
    });

    // Hide the original select
    $element.addClass('select2-hidden-accessible');
    $element.attr('aria-hidden', 'true');

    // Synchronize any monitored attributes
    this._syncAttributes();

    $element.data('select2', this);
  };

  Utils.Extend(Select2, Utils.Observable);

  Select2.prototype._generateId = function ($element) {
    var id = '';

    if ($element.attr('id') != null) {
      id = $element.attr('id');
    } else if ($element.attr('name') != null) {
      id = $element.attr('name') + '-' + Utils.generateChars(2);
    } else {
      id = Utils.generateChars(4);
    }

    id = id.replace(/(:|\.|\[|\]|,)/g, '');
    id = 'select2-' + id;

    return id;
  };

  Select2.prototype._placeContainer = function ($container) {
    $container.insertAfter(this.$element);

    var width = this._resolveWidth(this.$element, this.options.get('width'));

    if (width != null) {
      $container.css('width', width);
    }
  };

  Select2.prototype._resolveWidth = function ($element, method) {
    var WIDTH = /^width:(([-+]?([0-9]*\.)?[0-9]+)(px|em|ex|%|in|cm|mm|pt|pc))/i;

    if (method == 'resolve') {
      var styleWidth = this._resolveWidth($element, 'style');

      if (styleWidth != null) {
        return styleWidth;
      }

      return this._resolveWidth($element, 'element');
    }

    if (method == 'element') {
      var elementWidth = $element.outerWidth(false);

      if (elementWidth <= 0) {
        return 'auto';
      }

      return elementWidth + 'px';
    }

    if (method == 'style') {
      var style = $element.attr('style');

      if (typeof(style) !== 'string') {
        return null;
      }

      var attrs = style.split(';');

      for (var i = 0, l = attrs.length; i < l; i = i + 1) {
        var attr = attrs[i].replace(/\s/g, '');
        var matches = attr.match(WIDTH);

        if (matches !== null && matches.length >= 1) {
          return matches[1];
        }
      }

      return null;
    }

    return method;
  };

  Select2.prototype._bindAdapters = function () {
    this.dataAdapter.bind(this, this.$container);
    this.selection.bind(this, this.$container);

    this.dropdown.bind(this, this.$container);
    this.results.bind(this, this.$container);
  };

  Select2.prototype._registerDomEvents = function () {
    var self = this;

    this.$element.on('change.select2', function () {
      self.dataAdapter.current(function (data) {
        self.trigger('selection:update', {
          data: data
        });
      });
    });

    this.$element.on('focus.select2', function (evt) {
      self.trigger('focus', evt);
    });

    this._syncA = Utils.bind(this._syncAttributes, this);
    this._syncS = Utils.bind(this._syncSubtree, this);

    if (this.$element[0].attachEvent) {
      this.$element[0].attachEvent('onpropertychange', this._syncA);
    }

    var observer = window.MutationObserver ||
      window.WebKitMutationObserver ||
      window.MozMutationObserver
    ;

    if (observer != null) {
      this._observer = new observer(function (mutations) {
        $.each(mutations, self._syncA);
        $.each(mutations, self._syncS);
      });
      this._observer.observe(this.$element[0], {
        attributes: true,
        childList: true,
        subtree: false
      });
    } else if (this.$element[0].addEventListener) {
      this.$element[0].addEventListener(
        'DOMAttrModified',
        self._syncA,
        false
      );
      this.$element[0].addEventListener(
        'DOMNodeInserted',
        self._syncS,
        false
      );
      this.$element[0].addEventListener(
        'DOMNodeRemoved',
        self._syncS,
        false
      );
    }
  };

  Select2.prototype._registerDataEvents = function () {
    var self = this;

    this.dataAdapter.on('*', function (name, params) {
      self.trigger(name, params);
    });
  };

  Select2.prototype._registerSelectionEvents = function () {
    var self = this;
    var nonRelayEvents = ['toggle', 'focus'];

    this.selection.on('toggle', function () {
      self.toggleDropdown();
    });

    this.selection.on('focus', function (params) {
      self.focus(params);
    });

    this.selection.on('*', function (name, params) {
      if ($.inArray(name, nonRelayEvents) !== -1) {
        return;
      }

      self.trigger(name, params);
    });
  };

  Select2.prototype._registerDropdownEvents = function () {
    var self = this;

    this.dropdown.on('*', function (name, params) {
      self.trigger(name, params);
    });
  };

  Select2.prototype._registerResultsEvents = function () {
    var self = this;

    this.results.on('*', function (name, params) {
      self.trigger(name, params);
    });
  };

  Select2.prototype._registerEvents = function () {
    var self = this;

    this.on('open', function () {
      self.$container.addClass('select2-container--open');
    });

    this.on('close', function () {
      self.$container.removeClass('select2-container--open');
    });

    this.on('enable', function () {
      self.$container.removeClass('select2-container--disabled');
    });

    this.on('disable', function () {
      self.$container.addClass('select2-container--disabled');
    });

    this.on('blur', function () {
      self.$container.removeClass('select2-container--focus');
    });

    this.on('query', function (params) {
      if (!self.isOpen()) {
        self.trigger('open', {});
      }

      this.dataAdapter.query(params, function (data) {
        self.trigger('results:all', {
          data: data,
          query: params
        });
      });
    });

    this.on('query:append', function (params) {
      this.dataAdapter.query(params, function (data) {
        self.trigger('results:append', {
          data: data,
          query: params
        });
      });
    });

    this.on('keypress', function (evt) {
      var key = evt.which;

      if (self.isOpen()) {
        if (key === KEYS.ESC || key === KEYS.TAB ||
            (key === KEYS.UP && evt.altKey)) {
          self.close();

          evt.preventDefault();
        } else if (key === KEYS.ENTER) {
          self.trigger('results:select', {});

          evt.preventDefault();
        } else if ((key === KEYS.SPACE && evt.ctrlKey)) {
          self.trigger('results:toggle', {});

          evt.preventDefault();
        } else if (key === KEYS.UP) {
          self.trigger('results:previous', {});

          evt.preventDefault();
        } else if (key === KEYS.DOWN) {
          self.trigger('results:next', {});

          evt.preventDefault();
        }
      } else {
        if (key === KEYS.ENTER || key === KEYS.SPACE ||
            (key === KEYS.DOWN && evt.altKey)) {
          self.open();

          evt.preventDefault();
        }
      }
    });
  };

  Select2.prototype._syncAttributes = function () {
    this.options.set('disabled', this.$element.prop('disabled'));

    if (this.options.get('disabled')) {
      if (this.isOpen()) {
        this.close();
      }

      this.trigger('disable', {});
    } else {
      this.trigger('enable', {});
    }
  };

  Select2.prototype._syncSubtree = function (evt, mutations) {
    var changed = false;
    var self = this;

    // Ignore any mutation events raised for elements that aren't options or
    // optgroups. This handles the case when the select element is destroyed
    if (
      evt && evt.target && (
        evt.target.nodeName !== 'OPTION' && evt.target.nodeName !== 'OPTGROUP'
      )
    ) {
      return;
    }

    if (!mutations) {
      // If mutation events aren't supported, then we can only assume that the
      // change affected the selections
      changed = true;
    } else if (mutations.addedNodes && mutations.addedNodes.length > 0) {
      for (var n = 0; n < mutations.addedNodes.length; n++) {
        var node = mutations.addedNodes[n];

        if (node.selected) {
          changed = true;
        }
      }
    } else if (mutations.removedNodes && mutations.removedNodes.length > 0) {
      changed = true;
    }

    // Only re-pull the data if we think there is a change
    if (changed) {
      this.dataAdapter.current(function (currentData) {
        self.trigger('selection:update', {
          data: currentData
        });
      });
    }
  };

  /**
   * Override the trigger method to automatically trigger pre-events when
   * there are events that can be prevented.
   */
  Select2.prototype.trigger = function (name, args) {
    var actualTrigger = Select2.__super__.trigger;
    var preTriggerMap = {
      'open': 'opening',
      'close': 'closing',
      'select': 'selecting',
      'unselect': 'unselecting'
    };

    if (args === undefined) {
      args = {};
    }

    if (name in preTriggerMap) {
      var preTriggerName = preTriggerMap[name];
      var preTriggerArgs = {
        prevented: false,
        name: name,
        args: args
      };

      actualTrigger.call(this, preTriggerName, preTriggerArgs);

      if (preTriggerArgs.prevented) {
        args.prevented = true;

        return;
      }
    }

    actualTrigger.call(this, name, args);
  };

  Select2.prototype.toggleDropdown = function () {
    if (this.options.get('disabled')) {
      return;
    }

    if (this.isOpen()) {
      this.close();
    } else {
      this.open();
    }
  };

  Select2.prototype.open = function () {
    if (this.isOpen()) {
      return;
    }

    this.trigger('query', {});
  };

  Select2.prototype.close = function () {
    if (!this.isOpen()) {
      return;
    }

    this.trigger('close', {});
  };

  Select2.prototype.isOpen = function () {
    return this.$container.hasClass('select2-container--open');
  };

  Select2.prototype.hasFocus = function () {
    return this.$container.hasClass('select2-container--focus');
  };

  Select2.prototype.focus = function (data) {
    // No need to re-trigger focus events if we are already focused
    if (this.hasFocus()) {
      return;
    }

    this.$container.addClass('select2-container--focus');
    this.trigger('focus', {});
  };

  Select2.prototype.enable = function (args) {
    if (this.options.get('debug') && window.console && console.warn) {
      console.warn(
        'Select2: The `select2("enable")` method has been deprecated and will' +
        ' be removed in later Select2 versions. Use $element.prop("disabled")' +
        ' instead.'
      );
    }

    if (args == null || args.length === 0) {
      args = [true];
    }

    var disabled = !args[0];

    this.$element.prop('disabled', disabled);
  };

  Select2.prototype.data = function () {
    if (this.options.get('debug') &&
        arguments.length > 0 && window.console && console.warn) {
      console.warn(
        'Select2: Data can no longer be set using `select2("data")`. You ' +
        'should consider setting the value instead using `$element.val()`.'
      );
    }

    var data = [];

    this.dataAdapter.current(function (currentData) {
      data = currentData;
    });

    return data;
  };

  Select2.prototype.val = function (args) {
    if (this.options.get('debug') && window.console && console.warn) {
      console.warn(
        'Select2: The `select2("val")` method has been deprecated and will be' +
        ' removed in later Select2 versions. Use $element.val() instead.'
      );
    }

    if (args == null || args.length === 0) {
      return this.$element.val();
    }

    var newVal = args[0];

    if ($.isArray(newVal)) {
      newVal = $.map(newVal, function (obj) {
        return obj.toString();
      });
    }

    this.$element.val(newVal).trigger('change');
  };

  Select2.prototype.destroy = function () {
    this.$container.remove();

    if (this.$element[0].detachEvent) {
      this.$element[0].detachEvent('onpropertychange', this._syncA);
    }

    if (this._observer != null) {
      this._observer.disconnect();
      this._observer = null;
    } else if (this.$element[0].removeEventListener) {
      this.$element[0]
        .removeEventListener('DOMAttrModified', this._syncA, false);
      this.$element[0]
        .removeEventListener('DOMNodeInserted', this._syncS, false);
      this.$element[0]
        .removeEventListener('DOMNodeRemoved', this._syncS, false);
    }

    this._syncA = null;
    this._syncS = null;

    this.$element.off('.select2');
    this.$element.attr('tabindex', this.$element.data('old-tabindex'));

    this.$element.removeClass('select2-hidden-accessible');
    this.$element.attr('aria-hidden', 'false');
    this.$element.removeData('select2');

    this.dataAdapter.destroy();
    this.selection.destroy();
    this.dropdown.destroy();
    this.results.destroy();

    this.dataAdapter = null;
    this.selection = null;
    this.dropdown = null;
    this.results = null;
  };

  Select2.prototype.render = function () {
    var $container = $(
      '<span class="select2 select2-container">' +
        '<span class="selection"></span>' +
        '<span class="dropdown-wrapper" aria-hidden="true"></span>' +
      '</span>'
    );

    $container.attr('dir', this.options.get('dir'));

    this.$container = $container;

    this.$container.addClass('select2-container--' + this.options.get('theme'));

    $container.data('element', this.$element);

    return $container;
  };

  return Select2;
});

S2.define('select2/compat/utils',[
  'jquery'
], function ($) {
  function syncCssClasses ($dest, $src, adapter) {
    var classes, replacements = [], adapted;

    classes = $.trim($dest.attr('class'));

    if (classes) {
      classes = '' + classes; // for IE which returns object

      $(classes.split(/\s+/)).each(function () {
        // Save all Select2 classes
        if (this.indexOf('select2-') === 0) {
          replacements.push(this);
        }
      });
    }

    classes = $.trim($src.attr('class'));

    if (classes) {
      classes = '' + classes; // for IE which returns object

      $(classes.split(/\s+/)).each(function () {
        // Only adapt non-Select2 classes
        if (this.indexOf('select2-') !== 0) {
          adapted = adapter(this);

          if (adapted != null) {
            replacements.push(adapted);
          }
        }
      });
    }

    $dest.attr('class', replacements.join(' '));
  }

  return {
    syncCssClasses: syncCssClasses
  };
});

S2.define('select2/compat/containerCss',[
  'jquery',
  './utils'
], function ($, CompatUtils) {
  // No-op CSS adapter that discards all classes by default
  function _containerAdapter (clazz) {
    return null;
  }

  function ContainerCSS () { }

  ContainerCSS.prototype.render = function (decorated) {
    var $container = decorated.call(this);

    var containerCssClass = this.options.get('containerCssClass') || '';

    if ($.isFunction(containerCssClass)) {
      containerCssClass = containerCssClass(this.$element);
    }

    var containerCssAdapter = this.options.get('adaptContainerCssClass');
    containerCssAdapter = containerCssAdapter || _containerAdapter;

    if (containerCssClass.indexOf(':all:') !== -1) {
      containerCssClass = containerCssClass.replace(':all:', '');

      var _cssAdapter = containerCssAdapter;

      containerCssAdapter = function (clazz) {
        var adapted = _cssAdapter(clazz);

        if (adapted != null) {
          // Append the old one along with the adapted one
          return adapted + ' ' + clazz;
        }

        return clazz;
      };
    }

    var containerCss = this.options.get('containerCss') || {};

    if ($.isFunction(containerCss)) {
      containerCss = containerCss(this.$element);
    }

    CompatUtils.syncCssClasses($container, this.$element, containerCssAdapter);

    $container.css(containerCss);
    $container.addClass(containerCssClass);

    return $container;
  };

  return ContainerCSS;
});

S2.define('select2/compat/dropdownCss',[
  'jquery',
  './utils'
], function ($, CompatUtils) {
  // No-op CSS adapter that discards all classes by default
  function _dropdownAdapter (clazz) {
    return null;
  }

  function DropdownCSS () { }

  DropdownCSS.prototype.render = function (decorated) {
    var $dropdown = decorated.call(this);

    var dropdownCssClass = this.options.get('dropdownCssClass') || '';

    if ($.isFunction(dropdownCssClass)) {
      dropdownCssClass = dropdownCssClass(this.$element);
    }

    var dropdownCssAdapter = this.options.get('adaptDropdownCssClass');
    dropdownCssAdapter = dropdownCssAdapter || _dropdownAdapter;

    if (dropdownCssClass.indexOf(':all:') !== -1) {
      dropdownCssClass = dropdownCssClass.replace(':all:', '');

      var _cssAdapter = dropdownCssAdapter;

      dropdownCssAdapter = function (clazz) {
        var adapted = _cssAdapter(clazz);

        if (adapted != null) {
          // Append the old one along with the adapted one
          return adapted + ' ' + clazz;
        }

        return clazz;
      };
    }

    var dropdownCss = this.options.get('dropdownCss') || {};

    if ($.isFunction(dropdownCss)) {
      dropdownCss = dropdownCss(this.$element);
    }

    CompatUtils.syncCssClasses($dropdown, this.$element, dropdownCssAdapter);

    $dropdown.css(dropdownCss);
    $dropdown.addClass(dropdownCssClass);

    return $dropdown;
  };

  return DropdownCSS;
});

S2.define('select2/compat/initSelection',[
  'jquery'
], function ($) {
  function InitSelection (decorated, $element, options) {
    if (options.get('debug') && window.console && console.warn) {
      console.warn(
        'Select2: The `initSelection` option has been deprecated in favor' +
        ' of a custom data adapter that overrides the `current` method. ' +
        'This method is now called multiple times instead of a single ' +
        'time when the instance is initialized. Support will be removed ' +
        'for the `initSelection` option in future versions of Select2'
      );
    }

    this.initSelection = options.get('initSelection');
    this._isInitialized = false;

    decorated.call(this, $element, options);
  }

  InitSelection.prototype.current = function (decorated, callback) {
    var self = this;

    if (this._isInitialized) {
      decorated.call(this, callback);

      return;
    }

    this.initSelection.call(null, this.$element, function (data) {
      self._isInitialized = true;

      if (!$.isArray(data)) {
        data = [data];
      }

      callback(data);
    });
  };

  return InitSelection;
});

S2.define('select2/compat/inputData',[
  'jquery'
], function ($) {
  function InputData (decorated, $element, options) {
    this._currentData = [];
    this._valueSeparator = options.get('valueSeparator') || ',';

    if ($element.prop('type') === 'hidden') {
      if (options.get('debug') && console && console.warn) {
        console.warn(
          'Select2: Using a hidden input with Select2 is no longer ' +
          'supported and may stop working in the future. It is recommended ' +
          'to use a `<select>` element instead.'
        );
      }
    }

    decorated.call(this, $element, options);
  }

  InputData.prototype.current = function (_, callback) {
    function getSelected (data, selectedIds) {
      var selected = [];

      if (data.selected || $.inArray(data.id, selectedIds) !== -1) {
        data.selected = true;
        selected.push(data);
      } else {
        data.selected = false;
      }

      if (data.children) {
        selected.push.apply(selected, getSelected(data.children, selectedIds));
      }

      return selected;
    }

    var selected = [];

    for (var d = 0; d < this._currentData.length; d++) {
      var data = this._currentData[d];

      selected.push.apply(
        selected,
        getSelected(
          data,
          this.$element.val().split(
            this._valueSeparator
          )
        )
      );
    }

    callback(selected);
  };

  InputData.prototype.select = function (_, data) {
    if (!this.options.get('multiple')) {
      this.current(function (allData) {
        $.map(allData, function (data) {
          data.selected = false;
        });
      });

      this.$element.val(data.id);
      this.$element.trigger('change');
    } else {
      var value = this.$element.val();
      value += this._valueSeparator + data.id;

      this.$element.val(value);
      this.$element.trigger('change');
    }
  };

  InputData.prototype.unselect = function (_, data) {
    var self = this;

    data.selected = false;

    this.current(function (allData) {
      var values = [];

      for (var d = 0; d < allData.length; d++) {
        var item = allData[d];

        if (data.id == item.id) {
          continue;
        }

        values.push(item.id);
      }

      self.$element.val(values.join(self._valueSeparator));
      self.$element.trigger('change');
    });
  };

  InputData.prototype.query = function (_, params, callback) {
    var results = [];

    for (var d = 0; d < this._currentData.length; d++) {
      var data = this._currentData[d];

      var matches = this.matches(params, data);

      if (matches !== null) {
        results.push(matches);
      }
    }

    callback({
      results: results
    });
  };

  InputData.prototype.addOptions = function (_, $options) {
    var options = $.map($options, function ($option) {
      return $.data($option[0], 'data');
    });

    this._currentData.push.apply(this._currentData, options);
  };

  return InputData;
});

S2.define('select2/compat/matcher',[
  'jquery'
], function ($) {
  function oldMatcher (matcher) {
    function wrappedMatcher (params, data) {
      var match = $.extend(true, {}, data);

      if (params.term == null || $.trim(params.term) === '') {
        return match;
      }

      if (data.children) {
        for (var c = data.children.length - 1; c >= 0; c--) {
          var child = data.children[c];

          // Check if the child object matches
          // The old matcher returned a boolean true or false
          var doesMatch = matcher(params.term, child.text, child);

          // If the child didn't match, pop it off
          if (!doesMatch) {
            match.children.splice(c, 1);
          }
        }

        if (match.children.length > 0) {
          return match;
        }
      }

      if (matcher(params.term, data.text, data)) {
        return match;
      }

      return null;
    }

    return wrappedMatcher;
  }

  return oldMatcher;
});

S2.define('select2/compat/query',[

], function () {
  function Query (decorated, $element, options) {
    if (options.get('debug') && window.console && console.warn) {
      console.warn(
        'Select2: The `query` option has been deprecated in favor of a ' +
        'custom data adapter that overrides the `query` method. Support ' +
        'will be removed for the `query` option in future versions of ' +
        'Select2.'
      );
    }

    decorated.call(this, $element, options);
  }

  Query.prototype.query = function (_, params, callback) {
    params.callback = callback;

    var query = this.options.get('query');

    query.call(null, params);
  };

  return Query;
});

S2.define('select2/dropdown/attachContainer',[

], function () {
  function AttachContainer (decorated, $element, options) {
    decorated.call(this, $element, options);
  }

  AttachContainer.prototype.position =
    function (decorated, $dropdown, $container) {
    var $dropdownContainer = $container.find('.dropdown-wrapper');
    $dropdownContainer.append($dropdown);

    $dropdown.addClass('select2-dropdown--below');
    $container.addClass('select2-container--below');
  };

  return AttachContainer;
});

S2.define('select2/dropdown/stopPropagation',[

], function () {
  function StopPropagation () { }

  StopPropagation.prototype.bind = function (decorated, container, $container) {
    decorated.call(this, container, $container);

    var stoppedEvents = [
    'blur',
    'change',
    'click',
    'dblclick',
    'focus',
    'focusin',
    'focusout',
    'input',
    'keydown',
    'keyup',
    'keypress',
    'mousedown',
    'mouseenter',
    'mouseleave',
    'mousemove',
    'mouseover',
    'mouseup',
    'search',
    'touchend',
    'touchstart'
    ];

    this.$dropdown.on(stoppedEvents.join(' '), function (evt) {
      evt.stopPropagation();
    });
  };

  return StopPropagation;
});

S2.define('select2/selection/stopPropagation',[

], function () {
  function StopPropagation () { }

  StopPropagation.prototype.bind = function (decorated, container, $container) {
    decorated.call(this, container, $container);

    var stoppedEvents = [
      'blur',
      'change',
      'click',
      'dblclick',
      'focus',
      'focusin',
      'focusout',
      'input',
      'keydown',
      'keyup',
      'keypress',
      'mousedown',
      'mouseenter',
      'mouseleave',
      'mousemove',
      'mouseover',
      'mouseup',
      'search',
      'touchend',
      'touchstart'
    ];

    this.$selection.on(stoppedEvents.join(' '), function (evt) {
      evt.stopPropagation();
    });
  };

  return StopPropagation;
});

/*!
 * jQuery Mousewheel 3.1.13
 *
 * Copyright jQuery Foundation and other contributors
 * Released under the MIT license
 * http://jquery.org/license
 */

(function (factory) {
    if ( typeof S2.define === 'function' && S2.define.amd ) {
        // AMD. Register as an anonymous module.
        S2.define('jquery-mousewheel',['jquery'], factory);
    } else if (typeof exports === 'object') {
        // Node/CommonJS style for Browserify
        module.exports = factory;
    } else {
        // Browser globals
        factory(jQuery);
    }
}(function ($) {

    var toFix  = ['wheel', 'mousewheel', 'DOMMouseScroll', 'MozMousePixelScroll'],
        toBind = ( 'onwheel' in document || document.documentMode >= 9 ) ?
                    ['wheel'] : ['mousewheel', 'DomMouseScroll', 'MozMousePixelScroll'],
        slice  = Array.prototype.slice,
        nullLowestDeltaTimeout, lowestDelta;

    if ( $.event.fixHooks ) {
        for ( var i = toFix.length; i; ) {
            $.event.fixHooks[ toFix[--i] ] = $.event.mouseHooks;
        }
    }

    var special = $.event.special.mousewheel = {
        version: '3.1.12',

        setup: function() {
            if ( this.addEventListener ) {
                for ( var i = toBind.length; i; ) {
                    this.addEventListener( toBind[--i], handler, false );
                }
            } else {
                this.onmousewheel = handler;
            }
            // Store the line height and page height for this particular element
            $.data(this, 'mousewheel-line-height', special.getLineHeight(this));
            $.data(this, 'mousewheel-page-height', special.getPageHeight(this));
        },

        teardown: function() {
            if ( this.removeEventListener ) {
                for ( var i = toBind.length; i; ) {
                    this.removeEventListener( toBind[--i], handler, false );
                }
            } else {
                this.onmousewheel = null;
            }
            // Clean up the data we added to the element
            $.removeData(this, 'mousewheel-line-height');
            $.removeData(this, 'mousewheel-page-height');
        },

        getLineHeight: function(elem) {
            var $elem = $(elem),
                $parent = $elem['offsetParent' in $.fn ? 'offsetParent' : 'parent']();
            if (!$parent.length) {
                $parent = $('body');
            }
            return parseInt($parent.css('fontSize'), 10) || parseInt($elem.css('fontSize'), 10) || 16;
        },

        getPageHeight: function(elem) {
            return $(elem).height();
        },

        settings: {
            adjustOldDeltas: true, // see shouldAdjustOldDeltas() below
            normalizeOffset: true  // calls getBoundingClientRect for each event
        }
    };

    $.fn.extend({
        mousewheel: function(fn) {
            return fn ? this.bind('mousewheel', fn) : this.trigger('mousewheel');
        },

        unmousewheel: function(fn) {
            return this.unbind('mousewheel', fn);
        }
    });


    function handler(event) {
        var orgEvent   = event || window.event,
            args       = slice.call(arguments, 1),
            delta      = 0,
            deltaX     = 0,
            deltaY     = 0,
            absDelta   = 0,
            offsetX    = 0,
            offsetY    = 0;
        event = $.event.fix(orgEvent);
        event.type = 'mousewheel';

        // Old school scrollwheel delta
        if ( 'detail'      in orgEvent ) { deltaY = orgEvent.detail * -1;      }
        if ( 'wheelDelta'  in orgEvent ) { deltaY = orgEvent.wheelDelta;       }
        if ( 'wheelDeltaY' in orgEvent ) { deltaY = orgEvent.wheelDeltaY;      }
        if ( 'wheelDeltaX' in orgEvent ) { deltaX = orgEvent.wheelDeltaX * -1; }

        // Firefox < 17 horizontal scrolling related to DOMMouseScroll event
        if ( 'axis' in orgEvent && orgEvent.axis === orgEvent.HORIZONTAL_AXIS ) {
            deltaX = deltaY * -1;
            deltaY = 0;
        }

        // Set delta to be deltaY or deltaX if deltaY is 0 for backwards compatabilitiy
        delta = deltaY === 0 ? deltaX : deltaY;

        // New school wheel delta (wheel event)
        if ( 'deltaY' in orgEvent ) {
            deltaY = orgEvent.deltaY * -1;
            delta  = deltaY;
        }
        if ( 'deltaX' in orgEvent ) {
            deltaX = orgEvent.deltaX;
            if ( deltaY === 0 ) { delta  = deltaX * -1; }
        }

        // No change actually happened, no reason to go any further
        if ( deltaY === 0 && deltaX === 0 ) { return; }

        // Need to convert lines and pages to pixels if we aren't already in pixels
        // There are three delta modes:
        //   * deltaMode 0 is by pixels, nothing to do
        //   * deltaMode 1 is by lines
        //   * deltaMode 2 is by pages
        if ( orgEvent.deltaMode === 1 ) {
            var lineHeight = $.data(this, 'mousewheel-line-height');
            delta  *= lineHeight;
            deltaY *= lineHeight;
            deltaX *= lineHeight;
        } else if ( orgEvent.deltaMode === 2 ) {
            var pageHeight = $.data(this, 'mousewheel-page-height');
            delta  *= pageHeight;
            deltaY *= pageHeight;
            deltaX *= pageHeight;
        }

        // Store lowest absolute delta to normalize the delta values
        absDelta = Math.max( Math.abs(deltaY), Math.abs(deltaX) );

        if ( !lowestDelta || absDelta < lowestDelta ) {
            lowestDelta = absDelta;

            // Adjust older deltas if necessary
            if ( shouldAdjustOldDeltas(orgEvent, absDelta) ) {
                lowestDelta /= 40;
            }
        }

        // Adjust older deltas if necessary
        if ( shouldAdjustOldDeltas(orgEvent, absDelta) ) {
            // Divide all the things by 40!
            delta  /= 40;
            deltaX /= 40;
            deltaY /= 40;
        }

        // Get a whole, normalized value for the deltas
        delta  = Math[ delta  >= 1 ? 'floor' : 'ceil' ](delta  / lowestDelta);
        deltaX = Math[ deltaX >= 1 ? 'floor' : 'ceil' ](deltaX / lowestDelta);
        deltaY = Math[ deltaY >= 1 ? 'floor' : 'ceil' ](deltaY / lowestDelta);

        // Normalise offsetX and offsetY properties
        if ( special.settings.normalizeOffset && this.getBoundingClientRect ) {
            var boundingRect = this.getBoundingClientRect();
            offsetX = event.clientX - boundingRect.left;
            offsetY = event.clientY - boundingRect.top;
        }

        // Add information to the event object
        event.deltaX = deltaX;
        event.deltaY = deltaY;
        event.deltaFactor = lowestDelta;
        event.offsetX = offsetX;
        event.offsetY = offsetY;
        // Go ahead and set deltaMode to 0 since we converted to pixels
        // Although this is a little odd since we overwrite the deltaX/Y
        // properties with normalized deltas.
        event.deltaMode = 0;

        // Add event and delta to the front of the arguments
        args.unshift(event, delta, deltaX, deltaY);

        // Clearout lowestDelta after sometime to better
        // handle multiple device types that give different
        // a different lowestDelta
        // Ex: trackpad = 3 and mouse wheel = 120
        if (nullLowestDeltaTimeout) { clearTimeout(nullLowestDeltaTimeout); }
        nullLowestDeltaTimeout = setTimeout(nullLowestDelta, 200);

        return ($.event.dispatch || $.event.handle).apply(this, args);
    }

    function nullLowestDelta() {
        lowestDelta = null;
    }

    function shouldAdjustOldDeltas(orgEvent, absDelta) {
        // If this is an older event and the delta is divisable by 120,
        // then we are assuming that the browser is treating this as an
        // older mouse wheel event and that we should divide the deltas
        // by 40 to try and get a more usable deltaFactor.
        // Side note, this actually impacts the reported scroll distance
        // in older browsers and can cause scrolling to be slower than native.
        // Turn this off by setting $.event.special.mousewheel.settings.adjustOldDeltas to false.
        return special.settings.adjustOldDeltas && orgEvent.type === 'mousewheel' && absDelta % 120 === 0;
    }

}));

S2.define('jquery.select2',[
  'jquery',
  'jquery-mousewheel',

  './select2/core',
  './select2/defaults'
], function ($, _, Select2, Defaults) {
  if ($.fn.select2 == null) {
    // All methods that should return the element
    var thisMethods = ['open', 'close', 'destroy'];

    $.fn.select2 = function (options) {
      options = options || {};

      if (typeof options === 'object') {
        this.each(function () {
          var instanceOptions = $.extend(true, {}, options);

          var instance = new Select2($(this), instanceOptions);
        });

        return this;
      } else if (typeof options === 'string') {
        var ret;
        var args = Array.prototype.slice.call(arguments, 1);

        this.each(function () {
          var instance = $(this).data('select2');

          if (instance == null && window.console && console.error) {
            console.error(
              'The select2(\'' + options + '\') method was called on an ' +
              'element that is not using Select2.'
            );
          }

          ret = instance[options].apply(instance, args);
        });

        // Check if we should be returning `this`
        if ($.inArray(options, thisMethods) > -1) {
          return this;
        }

        return ret;
      } else {
        throw new Error('Invalid arguments for Select2: ' + options);
      }
    };
  }

  if ($.fn.select2.defaults == null) {
    $.fn.select2.defaults = Defaults;
  }

  return Select2;
});

  // Return the AMD loader configuration so it can be used outside of this file
  return {
    define: S2.define,
    require: S2.require
  };
}());

  // Autoload the jQuery bindings
  // We know that all of the modules exist above this, so we're safe
  var select2 = S2.require('jquery.select2');

  // Hold the AMD module references on the jQuery function that was just loaded
  // This allows Select2 to use the internal loader outside of this file, such
  // as in the language files.
  jQuery.fn.select2.amd = S2;

  // Return the Select2 instance for anyone who is importing it.
  return select2;
}));
/*! iScroll v5.2.0-snapshot ~ (c) 2008-2017 Matteo Spinelli ~ http://cubiq.org/license */
(function (window, document, Math) {
  var rAF = window.requestAnimationFrame	||
    window.webkitRequestAnimationFrame	||
    window.mozRequestAnimationFrame		||
    window.oRequestAnimationFrame		||
    window.msRequestAnimationFrame		||
    function (callback) { window.setTimeout(callback, 1000 / 60); };
  
  var utils = (function () {
    var me = {};
  
    var _elementStyle = document.createElement('div').style;
    var _vendor = (function () {
      var vendors = ['t', 'webkitT', 'MozT', 'msT', 'OT'],
        transform,
        i = 0,
        l = vendors.length;
  
      for ( ; i < l; i++ ) {
        transform = vendors[i] + 'ransform';
        if ( transform in _elementStyle ) return vendors[i].substr(0, vendors[i].length-1);
      }
  
      return false;
    })();
  
    function _prefixStyle (style) {
      if ( _vendor === false ) return false;
      if ( _vendor === '' ) return style;
      return _vendor + style.charAt(0).toUpperCase() + style.substr(1);
    }
  
    me.getTime = Date.now || function getTime () { return new Date().getTime(); };
  
    me.extend = function (target, obj) {
      for ( var i in obj ) {
        target[i] = obj[i];
      }
    };
  
    me.addEvent = function (el, type, fn, capture) {
      el.addEventListener(type, fn, !!capture);
    };
  
    me.removeEvent = function (el, type, fn, capture) {
      el.removeEventListener(type, fn, !!capture);
    };
  
    me.prefixPointerEvent = function (pointerEvent) {
      return window.MSPointerEvent ?
        'MSPointer' + pointerEvent.charAt(7).toUpperCase() + pointerEvent.substr(8):
        pointerEvent;
    };
  
    me.momentum = function (current, start, time, lowerMargin, wrapperSize, deceleration) {
      var distance = current - start,
        speed = Math.abs(distance) / time,
        destination,
        duration;
  
      deceleration = deceleration === undefined ? 0.0006 : deceleration;
  
      destination = current + ( speed * speed ) / ( 2 * deceleration ) * ( distance < 0 ? -1 : 1 );
      duration = speed / deceleration;
  
      if ( destination < lowerMargin ) {
        destination = wrapperSize ? lowerMargin - ( wrapperSize / 2.5 * ( speed / 8 ) ) : lowerMargin;
        distance = Math.abs(destination - current);
        duration = distance / speed;
      } else if ( destination > 0 ) {
        destination = wrapperSize ? wrapperSize / 2.5 * ( speed / 8 ) : 0;
        distance = Math.abs(current) + destination;
        duration = distance / speed;
      }
  
      return {
        destination: Math.round(destination),
        duration: duration
      };
    };
  
    var _transform = _prefixStyle('transform');
  
    me.extend(me, {
      hasTransform: _transform !== false,
      hasPerspective: _prefixStyle('perspective') in _elementStyle,
      hasTouch: 'ontouchstart' in window,
      hasPointer: !!(window.PointerEvent || window.MSPointerEvent), // IE10 is prefixed
      hasTransition: _prefixStyle('transition') in _elementStyle
    });
  
    /*
    This should find all Android browsers lower than build 535.19 (both stock browser and webview)
    - galaxy S2 is ok
      - 2.3.6 : `AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1`
      - 4.0.4 : `AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30`
     - galaxy S3 is badAndroid (stock brower, webview)
       `AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30`
     - galaxy S4 is badAndroid (stock brower, webview)
       `AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30`
     - galaxy S5 is OK
       `AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Mobile Safari/537.36 (Chrome/)`
     - galaxy S6 is OK
       `AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Mobile Safari/537.36 (Chrome/)`
    */
    me.isBadAndroid = (function() {
      var appVersion = window.navigator.appVersion;
      // Android browser is not a chrome browser.
      if (/Android/.test(appVersion) && !(/Chrome\/\d/.test(appVersion))) {
        var safariVersion = appVersion.match(/Safari\/(\d+.\d)/);
        if(safariVersion && typeof safariVersion === "object" && safariVersion.length >= 2) {
          return parseFloat(safariVersion[1]) < 535.19;
        } else {
          return true;
        }
      } else {
        return false;
      }
    })();
  
    me.extend(me.style = {}, {
      transform: _transform,
      transitionTimingFunction: _prefixStyle('transitionTimingFunction'),
      transitionDuration: _prefixStyle('transitionDuration'),
      transitionDelay: _prefixStyle('transitionDelay'),
      transformOrigin: _prefixStyle('transformOrigin'),
      touchAction: _prefixStyle('touchAction')
    });
  
    me.hasClass = function (e, c) {
      var re = new RegExp("(^|\\s)" + c + "(\\s|$)");
      return re.test(e.className);
    };
  
    me.addClass = function (e, c) {
      if ( me.hasClass(e, c) ) {
        return;
      }
  
      var newclass = e.className.split(' ');
      newclass.push(c);
      e.className = newclass.join(' ');
    };
  
    me.removeClass = function (e, c) {
      if ( !me.hasClass(e, c) ) {
        return;
      }
  
      var re = new RegExp("(^|\\s)" + c + "(\\s|$)", 'g');
      e.className = e.className.replace(re, ' ');
    };
  
    me.offset = function (el) {
      var left = -el.offsetLeft,
        top = -el.offsetTop;
  
      // jshint -W084
      while (el = el.offsetParent) {
        left -= el.offsetLeft;
        top -= el.offsetTop;
      }
      // jshint +W084
  
      return {
        left: left,
        top: top
      };
    };
  
    me.preventDefaultException = function (el, exceptions) {
      for ( var i in exceptions ) {
        if ( exceptions[i].test(el[i]) ) {
          return true;
        }
      }
  
      return false;
    };
  
    me.extend(me.eventType = {}, {
      touchstart: 1,
      touchmove: 1,
      touchend: 1,
  
      mousedown: 2,
      mousemove: 2,
      mouseup: 2,
  
      pointerdown: 3,
      pointermove: 3,
      pointerup: 3,
  
      MSPointerDown: 3,
      MSPointerMove: 3,
      MSPointerUp: 3
    });
  
    me.extend(me.ease = {}, {
      quadratic: {
        style: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
        fn: function (k) {
          return k * ( 2 - k );
        }
      },
      circular: {
        style: 'cubic-bezier(0.1, 0.57, 0.1, 1)',	// Not properly "circular" but this looks better, it should be (0.075, 0.82, 0.165, 1)
        fn: function (k) {
          return Math.sqrt( 1 - ( --k * k ) );
        }
      },
      back: {
        style: 'cubic-bezier(0.175, 0.885, 0.32, 1.275)',
        fn: function (k) {
          var b = 4;
          return ( k = k - 1 ) * k * ( ( b + 1 ) * k + b ) + 1;
        }
      },
      bounce: {
        style: '',
        fn: function (k) {
          if ( ( k /= 1 ) < ( 1 / 2.75 ) ) {
            return 7.5625 * k * k;
          } else if ( k < ( 2 / 2.75 ) ) {
            return 7.5625 * ( k -= ( 1.5 / 2.75 ) ) * k + 0.75;
          } else if ( k < ( 2.5 / 2.75 ) ) {
            return 7.5625 * ( k -= ( 2.25 / 2.75 ) ) * k + 0.9375;
          } else {
            return 7.5625 * ( k -= ( 2.625 / 2.75 ) ) * k + 0.984375;
          }
        }
      },
      elastic: {
        style: '',
        fn: function (k) {
          var f = 0.22,
            e = 0.4;
  
          if ( k === 0 ) { return 0; }
          if ( k == 1 ) { return 1; }
  
          return ( e * Math.pow( 2, - 10 * k ) * Math.sin( ( k - f / 4 ) * ( 2 * Math.PI ) / f ) + 1 );
        }
      }
    });
  
    me.tap = function (e, eventName) {
      var ev = document.createEvent('Event');
      ev.initEvent(eventName, true, true);
      ev.pageX = e.pageX;
      ev.pageY = e.pageY;
      e.target.dispatchEvent(ev);
    };
  
    me.click = function (e) {
      var target = e.target,
        ev;
  
      if ( !(/(SELECT|INPUT|TEXTAREA)/i).test(target.tagName) ) {
        // https://developer.mozilla.org/en-US/docs/Web/API/MouseEvent/initMouseEvent
        // initMouseEvent is deprecated.
        ev = document.createEvent(window.MouseEvent ? 'MouseEvents' : 'Event');
        ev.initEvent('click', true, true);
        ev.view = e.view || window;
        ev.detail = 1;
        ev.screenX = target.screenX || 0;
        ev.screenY = target.screenY || 0;
        ev.clientX = target.clientX || 0;
        ev.clientY = target.clientY || 0;
        ev.ctrlKey = !!e.ctrlKey;
        ev.altKey = !!e.altKey;
        ev.shiftKey = !!e.shiftKey;
        ev.metaKey = !!e.metaKey;
        ev.button = 0;
        ev.relatedTarget = null;
        ev._constructed = true;
        target.dispatchEvent(ev);
      }
    };
  
    me.getTouchAction = function(eventPassthrough, addPinch) {
      var touchAction = 'none';
      if ( eventPassthrough === 'vertical' ) {
        touchAction = 'pan-y';
      } else if (eventPassthrough === 'horizontal' ) {
        touchAction = 'pan-x';
      }
      if (addPinch && touchAction != 'none') {
        // add pinch-zoom support if the browser supports it, but if not (eg. Chrome <55) do nothing
        touchAction += ' pinch-zoom';
      }
      return touchAction;
    };
  
    me.getRect = function(el) {
      if (el instanceof SVGElement) {
        var rect = el.getBoundingClientRect();
        return {
          top : rect.top,
          left : rect.left,
          width : rect.width,
          height : rect.height
        };
      } else {
        return {
          top : el.offsetTop,
          left : el.offsetLeft,
          width : el.offsetWidth,
          height : el.offsetHeight
        };
      }
    };
  
    return me;
  })();
  function IScroll (el, options) {
    this.wrapper = typeof el == 'string' ? document.querySelector(el) : el;
    this.scroller = this.wrapper.children[0];
    this.scrollerStyle = this.scroller.style;		// cache style for better performance
  
    this.options = {
  
  // INSERT POINT: OPTIONS
      disablePointer : !utils.hasPointer,
      disableTouch : utils.hasPointer || !utils.hasTouch,
      disableMouse : utils.hasPointer || utils.hasTouch,
      startX: 0,
      startY: 0,
      scrollY: true,
      directionLockThreshold: 5,
      momentum: true,
  
      bounce: true,
      bounceTime: 600,
      bounceEasing: '',
  
      preventDefault: true,
      preventDefaultException: { tagName: /^(INPUT|TEXTAREA|BUTTON|SELECT)$/ },
  
      HWCompositing: true,
      useTransition: true,
      useTransform: true,
      bindToWrapper: typeof window.onmousedown === "undefined"
    };
  
    for ( var i in options ) {
      this.options[i] = options[i];
    }
  
    // Normalize options
    this.translateZ = this.options.HWCompositing && utils.hasPerspective ? ' translateZ(0)' : '';
  
    this.options.useTransition = utils.hasTransition && this.options.useTransition;
    this.options.useTransform = utils.hasTransform && this.options.useTransform;
  
    this.options.eventPassthrough = this.options.eventPassthrough === true ? 'vertical' : this.options.eventPassthrough;
    this.options.preventDefault = !this.options.eventPassthrough && this.options.preventDefault;
  
    // If you want eventPassthrough I have to lock one of the axes
    this.options.scrollY = this.options.eventPassthrough == 'vertical' ? false : this.options.scrollY;
    this.options.scrollX = this.options.eventPassthrough == 'horizontal' ? false : this.options.scrollX;
  
    // With eventPassthrough we also need lockDirection mechanism
    this.options.freeScroll = this.options.freeScroll && !this.options.eventPassthrough;
    this.options.directionLockThreshold = this.options.eventPassthrough ? 0 : this.options.directionLockThreshold;
  
    this.options.bounceEasing = typeof this.options.bounceEasing == 'string' ? utils.ease[this.options.bounceEasing] || utils.ease.circular : this.options.bounceEasing;
  
    this.options.resizePolling = this.options.resizePolling === undefined ? 60 : this.options.resizePolling;
  
    if ( this.options.tap === true ) {
      this.options.tap = 'tap';
    }
  
    // https://github.com/cubiq/iscroll/issues/1029
    if (!this.options.useTransition && !this.options.useTransform) {
      if(!(/relative|absolute/i).test(this.scrollerStyle.position)) {
        this.scrollerStyle.position = "relative";
      }
    }
  
  // INSERT POINT: NORMALIZATION
  
    // Some defaults
    this.x = 0;
    this.y = 0;
    this.directionX = 0;
    this.directionY = 0;
    this._events = {};
  
  // INSERT POINT: DEFAULTS
  
    this._init();
    this.refresh();
  
    this.scrollTo(this.options.startX, this.options.startY);
    this.enable();
  }
  
  IScroll.prototype = {
    version: '5.2.0-snapshot',
  
    _init: function () {
      this._initEvents();
  
  // INSERT POINT: _init
  
    },
  
    destroy: function () {
      this._initEvents(true);
      clearTimeout(this.resizeTimeout);
       this.resizeTimeout = null;
      this._execEvent('destroy');
    },
  
    _transitionEnd: function (e) {
      if ( e.target != this.scroller || !this.isInTransition ) {
        return;
      }
  
      this._transitionTime();
      if ( !this.resetPosition(this.options.bounceTime) ) {
        this.isInTransition = false;
        this._execEvent('scrollEnd');
      }
    },
  
    _start: function (e) {
      // React to left mouse button only
      if ( utils.eventType[e.type] != 1 ) {
        // for button property
        // http://unixpapa.com/js/mouse.html
        var button;
        if (!e.which) {
          /* IE case */
          button = (e.button < 2) ? 0 :
                   ((e.button == 4) ? 1 : 2);
        } else {
          /* All others */
          button = e.button;
        }
        if ( button !== 0 ) {
          return;
        }
      }
  
      if ( !this.enabled || (this.initiated && utils.eventType[e.type] !== this.initiated) ) {
        return;
      }
  
      if ( this.options.preventDefault && !utils.isBadAndroid && !utils.preventDefaultException(e.target, this.options.preventDefaultException) ) {
        e.preventDefault();
      }
  
      var point = e.touches ? e.touches[0] : e,
        pos;
  
      this.initiated	= utils.eventType[e.type];
      this.moved		= false;
      this.distX		= 0;
      this.distY		= 0;
      this.directionX = 0;
      this.directionY = 0;
      this.directionLocked = 0;
  
      this.startTime = utils.getTime();
  
      if ( this.options.useTransition && this.isInTransition ) {
        this._transitionTime();
        this.isInTransition = false;
        pos = this.getComputedPosition();
        this._translate(Math.round(pos.x), Math.round(pos.y));
        this._execEvent('scrollEnd');
      } else if ( !this.options.useTransition && this.isAnimating ) {
        this.isAnimating = false;
        this._execEvent('scrollEnd');
      }
  
      this.startX    = this.x;
      this.startY    = this.y;
      this.absStartX = this.x;
      this.absStartY = this.y;
      this.pointX    = point.pageX;
      this.pointY    = point.pageY;
  
      this._execEvent('beforeScrollStart');
    },
  
    _move: function (e) {
      if ( !this.enabled || utils.eventType[e.type] !== this.initiated ) {
        return;
      }
  
      if ( this.options.preventDefault ) {	// increases performance on Android? TODO: check!
        e.preventDefault();
      }
  
      var point		= e.touches ? e.touches[0] : e,
        deltaX		= point.pageX - this.pointX,
        deltaY		= point.pageY - this.pointY,
        timestamp	= utils.getTime(),
        newX, newY,
        absDistX, absDistY;
  
      this.pointX		= point.pageX;
      this.pointY		= point.pageY;
  
      this.distX		+= deltaX;
      this.distY		+= deltaY;
      absDistX		= Math.abs(this.distX);
      absDistY		= Math.abs(this.distY);
  
      // We need to move at least 10 pixels for the scrolling to initiate
      if ( timestamp - this.endTime > 300 && (absDistX < 10 && absDistY < 10) ) {
        return;
      }
  
      // If you are scrolling in one direction lock the other
      if ( !this.directionLocked && !this.options.freeScroll ) {
        if ( absDistX > absDistY + this.options.directionLockThreshold ) {
          this.directionLocked = 'h';		// lock horizontally
        } else if ( absDistY >= absDistX + this.options.directionLockThreshold ) {
          this.directionLocked = 'v';		// lock vertically
        } else {
          this.directionLocked = 'n';		// no lock
        }
      }
  
      if ( this.directionLocked == 'h' ) {
        if ( this.options.eventPassthrough == 'vertical' ) {
          e.preventDefault();
        } else if ( this.options.eventPassthrough == 'horizontal' ) {
          this.initiated = false;
          return;
        }
  
        deltaY = 0;
      } else if ( this.directionLocked == 'v' ) {
        if ( this.options.eventPassthrough == 'horizontal' ) {
          e.preventDefault();
        } else if ( this.options.eventPassthrough == 'vertical' ) {
          this.initiated = false;
          return;
        }
  
        deltaX = 0;
      }
  
      deltaX = this.hasHorizontalScroll ? deltaX : 0;
      deltaY = this.hasVerticalScroll ? deltaY : 0;
  
      newX = this.x + deltaX;
      newY = this.y + deltaY;
  
      // Slow down if outside of the boundaries
      if ( newX > 0 || newX < this.maxScrollX ) {
        newX = this.options.bounce ? this.x + deltaX / 3 : newX > 0 ? 0 : this.maxScrollX;
      }
      if ( newY > 0 || newY < this.maxScrollY ) {
        newY = this.options.bounce ? this.y + deltaY / 3 : newY > 0 ? 0 : this.maxScrollY;
      }
  
      this.directionX = deltaX > 0 ? -1 : deltaX < 0 ? 1 : 0;
      this.directionY = deltaY > 0 ? -1 : deltaY < 0 ? 1 : 0;
  
      if ( !this.moved ) {
        this._execEvent('scrollStart');
      }
  
      this.moved = true;
  
      this._translate(newX, newY);
  
  /* REPLACE START: _move */
  
      if ( timestamp - this.startTime > 300 ) {
        this.startTime = timestamp;
        this.startX = this.x;
        this.startY = this.y;
      }
  
  /* REPLACE END: _move */
  
    },
  
    _end: function (e) {
      if ( !this.enabled || utils.eventType[e.type] !== this.initiated ) {
        return;
      }
  
      if ( this.options.preventDefault && !utils.preventDefaultException(e.target, this.options.preventDefaultException) ) {
        e.preventDefault();
      }
  
      var point = e.changedTouches ? e.changedTouches[0] : e,
        momentumX,
        momentumY,
        duration = utils.getTime() - this.startTime,
        newX = Math.round(this.x),
        newY = Math.round(this.y),
        distanceX = Math.abs(newX - this.startX),
        distanceY = Math.abs(newY - this.startY),
        time = 0,
        easing = '';
  
      this.isInTransition = 0;
      this.initiated = 0;
      this.endTime = utils.getTime();
  
      // reset if we are outside of the boundaries
      if ( this.resetPosition(this.options.bounceTime) ) {
        return;
      }
  
      this.scrollTo(newX, newY);	// ensures that the last position is rounded
  
      // we scrolled less than 10 pixels
      if ( !this.moved ) {
        if ( this.options.tap ) {
          utils.tap(e, this.options.tap);
        }
  
        if ( this.options.click ) {
          utils.click(e);
        }
  
        this._execEvent('scrollCancel');
        return;
      }
  
      if ( this._events.flick && duration < 200 && distanceX < 100 && distanceY < 100 ) {
        this._execEvent('flick');
        return;
      }
  
      // start momentum animation if needed
      if ( this.options.momentum && duration < 300 ) {
        momentumX = this.hasHorizontalScroll ? utils.momentum(this.x, this.startX, duration, this.maxScrollX, this.options.bounce ? this.wrapperWidth : 0, this.options.deceleration) : { destination: newX, duration: 0 };
        momentumY = this.hasVerticalScroll ? utils.momentum(this.y, this.startY, duration, this.maxScrollY, this.options.bounce ? this.wrapperHeight : 0, this.options.deceleration) : { destination: newY, duration: 0 };
        newX = momentumX.destination;
        newY = momentumY.destination;
        time = Math.max(momentumX.duration, momentumY.duration);
        this.isInTransition = 1;
      }
  
  // INSERT POINT: _end
  
      if ( newX != this.x || newY != this.y ) {
        // change easing function when scroller goes out of the boundaries
        if ( newX > 0 || newX < this.maxScrollX || newY > 0 || newY < this.maxScrollY ) {
          easing = utils.ease.quadratic;
        }
  
        this.scrollTo(newX, newY, time, easing);
        return;
      }
  
      this._execEvent('scrollEnd');
    },
  
    _resize: function () {
      var that = this;
  
      clearTimeout(this.resizeTimeout);
  
      this.resizeTimeout = setTimeout(function () {
        that.refresh();
      }, this.options.resizePolling);
    },
  
    resetPosition: function (time) {
      var x = this.x,
        y = this.y;
  
      time = time || 0;
  
      if ( !this.hasHorizontalScroll || this.x > 0 ) {
        x = 0;
      } else if ( this.x < this.maxScrollX ) {
        x = this.maxScrollX;
      }
  
      if ( !this.hasVerticalScroll || this.y > 0 ) {
        y = 0;
      } else if ( this.y < this.maxScrollY ) {
        y = this.maxScrollY;
      }
  
      if ( x == this.x && y == this.y ) {
        return false;
      }
  
      this.scrollTo(x, y, time, this.options.bounceEasing);
  
      return true;
    },
  
    disable: function () {
      this.enabled = false;
    },
  
    enable: function () {
      this.enabled = true;
    },
  
    refresh: function () {
      utils.getRect(this.wrapper);		// Force reflow
  
      this.wrapperWidth	= this.wrapper.clientWidth;
      this.wrapperHeight	= this.wrapper.clientHeight;
  
      var rect = utils.getRect(this.scroller);
  /* REPLACE START: refresh */
  
      this.scrollerWidth	= rect.width;
      this.scrollerHeight	= rect.height;
  
      this.maxScrollX		= this.wrapperWidth - this.scrollerWidth;
      this.maxScrollY		= this.wrapperHeight - this.scrollerHeight;
  
  /* REPLACE END: refresh */
  
      this.hasHorizontalScroll	= this.options.scrollX && this.maxScrollX < 0;
      this.hasVerticalScroll		= this.options.scrollY && this.maxScrollY < 0;
      
      if ( !this.hasHorizontalScroll ) {
        this.maxScrollX = 0;
        this.scrollerWidth = this.wrapperWidth;
      }
  
      if ( !this.hasVerticalScroll ) {
        this.maxScrollY = 0;
        this.scrollerHeight = this.wrapperHeight;
      }
  
      this.endTime = 0;
      this.directionX = 0;
      this.directionY = 0;
      
      if(utils.hasPointer && !this.options.disablePointer) {
        // The wrapper should have `touchAction` property for using pointerEvent.
        this.wrapper.style[utils.style.touchAction] = utils.getTouchAction(this.options.eventPassthrough, true);
  
        // case. not support 'pinch-zoom'
        // https://github.com/cubiq/iscroll/issues/1118#issuecomment-270057583
        if (!this.wrapper.style[utils.style.touchAction]) {
          this.wrapper.style[utils.style.touchAction] = utils.getTouchAction(this.options.eventPassthrough, false);
        }
      }
      this.wrapperOffset = utils.offset(this.wrapper);
  
      this._execEvent('refresh');
  
      this.resetPosition();
  
  // INSERT POINT: _refresh
  
    },	
  
    on: function (type, fn) {
      if ( !this._events[type] ) {
        this._events[type] = [];
      }
  
      this._events[type].push(fn);
    },
  
    off: function (type, fn) {
      if ( !this._events[type] ) {
        return;
      }
  
      var index = this._events[type].indexOf(fn);
  
      if ( index > -1 ) {
        this._events[type].splice(index, 1);
      }
    },
  
    _execEvent: function (type) {
      if ( !this._events[type] ) {
        return;
      }
  
      var i = 0,
        l = this._events[type].length;
  
      if ( !l ) {
        return;
      }
  
      for ( ; i < l; i++ ) {
        this._events[type][i].apply(this, [].slice.call(arguments, 1));
      }
    },
  
    scrollBy: function (x, y, time, easing) {
      x = this.x + x;
      y = this.y + y;
      time = time || 0;
  
      this.scrollTo(x, y, time, easing);
    },
  
    scrollTo: function (x, y, time, easing) {
      easing = easing || utils.ease.circular;
  
      this.isInTransition = this.options.useTransition && time > 0;
      var transitionType = this.options.useTransition && easing.style;
      if ( !time || transitionType ) {
          if(transitionType) {
            this._transitionTimingFunction(easing.style);
            this._transitionTime(time);
          }
        this._translate(x, y);
      } else {
        this._animate(x, y, time, easing.fn);
      }
    },
  
    scrollToElement: function (el, time, offsetX, offsetY, easing) {
      el = el.nodeType ? el : this.scroller.querySelector(el);
  
      if ( !el ) {
        return;
      }
  
      var pos = utils.offset(el);
  
      pos.left -= this.wrapperOffset.left;
      pos.top  -= this.wrapperOffset.top;
  
      // if offsetX/Y are true we center the element to the screen
      var elRect = utils.getRect(el);
      var wrapperRect = utils.getRect(this.wrapper);
      if ( offsetX === true ) {
        offsetX = Math.round(elRect.width / 2 - wrapperRect.width / 2);
      }
      if ( offsetY === true ) {
        offsetY = Math.round(elRect.height / 2 - wrapperRect.height / 2);
      }
  
      pos.left -= offsetX || 0;
      pos.top  -= offsetY || 0;
  
      pos.left = pos.left > 0 ? 0 : pos.left < this.maxScrollX ? this.maxScrollX : pos.left;
      pos.top  = pos.top  > 0 ? 0 : pos.top  < this.maxScrollY ? this.maxScrollY : pos.top;
  
      time = time === undefined || time === null || time === 'auto' ? Math.max(Math.abs(this.x-pos.left), Math.abs(this.y-pos.top)) : time;
  
      this.scrollTo(pos.left, pos.top, time, easing);
    },
  
    _transitionTime: function (time) {
      if (!this.options.useTransition) {
        return;
      }
      time = time || 0;
      var durationProp = utils.style.transitionDuration;
      if(!durationProp) {
        return;
      }
  
      this.scrollerStyle[durationProp] = time + 'ms';
  
      if ( !time && utils.isBadAndroid ) {
        this.scrollerStyle[durationProp] = '0.0001ms';
        // remove 0.0001ms
        var self = this;
        rAF(function() {
          if(self.scrollerStyle[durationProp] === '0.0001ms') {
            self.scrollerStyle[durationProp] = '0s';
          }
        });
      }
  
  // INSERT POINT: _transitionTime
  
    },
  
    _transitionTimingFunction: function (easing) {
      this.scrollerStyle[utils.style.transitionTimingFunction] = easing;
  
  // INSERT POINT: _transitionTimingFunction
  
    },
  
    _translate: function (x, y) {
      if ( this.options.useTransform ) {
  
  /* REPLACE START: _translate */
  
        this.scrollerStyle[utils.style.transform] = 'translate(' + x + 'px,' + y + 'px)' + this.translateZ;
  
  /* REPLACE END: _translate */
  
      } else {
        x = Math.round(x);
        y = Math.round(y);
        this.scrollerStyle.left = x + 'px';
        this.scrollerStyle.top = y + 'px';
      }
  
      this.x = x;
      this.y = y;
  
  // INSERT POINT: _translate
  
    },
  
    _initEvents: function (remove) {
      var eventType = remove ? utils.removeEvent : utils.addEvent,
        target = this.options.bindToWrapper ? this.wrapper : window;
  
      eventType(window, 'orientationchange', this);
      eventType(window, 'resize', this);
  
      if ( this.options.click ) {
        eventType(this.wrapper, 'click', this, true);
      }
  
      if ( !this.options.disableMouse ) {
        eventType(this.wrapper, 'mousedown', this);
        eventType(target, 'mousemove', this);
        eventType(target, 'mousecancel', this);
        eventType(target, 'mouseup', this);
      }
  
      if ( utils.hasPointer && !this.options.disablePointer ) {
        eventType(this.wrapper, utils.prefixPointerEvent('pointerdown'), this);
        eventType(target, utils.prefixPointerEvent('pointermove'), this);
        eventType(target, utils.prefixPointerEvent('pointercancel'), this);
        eventType(target, utils.prefixPointerEvent('pointerup'), this);
      }
  
      if ( utils.hasTouch && !this.options.disableTouch ) {
        eventType(this.wrapper, 'touchstart', this);
        eventType(target, 'touchmove', this);
        eventType(target, 'touchcancel', this);
        eventType(target, 'touchend', this);
      }
  
      eventType(this.scroller, 'transitionend', this);
      eventType(this.scroller, 'webkitTransitionEnd', this);
      eventType(this.scroller, 'oTransitionEnd', this);
      eventType(this.scroller, 'MSTransitionEnd', this);
    },
  
    getComputedPosition: function () {
      var matrix = window.getComputedStyle(this.scroller, null),
        x, y;
  
      if ( this.options.useTransform ) {
        matrix = matrix[utils.style.transform].split(')')[0].split(', ');
        x = +(matrix[12] || matrix[4]);
        y = +(matrix[13] || matrix[5]);
      } else {
        x = +matrix.left.replace(/[^-\d.]/g, '');
        y = +matrix.top.replace(/[^-\d.]/g, '');
      }
  
      return { x: x, y: y };
    },
    _animate: function (destX, destY, duration, easingFn) {
      var that = this,
        startX = this.x,
        startY = this.y,
        startTime = utils.getTime(),
        destTime = startTime + duration;
  
      function step () {
        var now = utils.getTime(),
          newX, newY,
          easing;
  
        if ( now >= destTime ) {
          that.isAnimating = false;
          that._translate(destX, destY);
  
          if ( !that.resetPosition(that.options.bounceTime) ) {
            that._execEvent('scrollEnd');
          }
  
          return;
        }
  
        now = ( now - startTime ) / duration;
        easing = easingFn(now);
        newX = ( destX - startX ) * easing + startX;
        newY = ( destY - startY ) * easing + startY;
        that._translate(newX, newY);
  
        if ( that.isAnimating ) {
          rAF(step);
        }
      }
  
      this.isAnimating = true;
      step();
    },
    handleEvent: function (e) {
      switch ( e.type ) {
        case 'touchstart':
        case 'pointerdown':
        case 'MSPointerDown':
        case 'mousedown':
          this._start(e);
          break;
        case 'touchmove':
        case 'pointermove':
        case 'MSPointerMove':
        case 'mousemove':
          this._move(e);
          break;
        case 'touchend':
        case 'pointerup':
        case 'MSPointerUp':
        case 'mouseup':
        case 'touchcancel':
        case 'pointercancel':
        case 'MSPointerCancel':
        case 'mousecancel':
          this._end(e);
          break;
        case 'orientationchange':
        case 'resize':
          this._resize();
          break;
        case 'transitionend':
        case 'webkitTransitionEnd':
        case 'oTransitionEnd':
        case 'MSTransitionEnd':
          this._transitionEnd(e);
          break;
        case 'wheel':
        case 'DOMMouseScroll':
        case 'mousewheel':
          this._wheel(e);
          break;
        case 'keydown':
          this._key(e);
          break;
        case 'click':
          if ( this.enabled && !e._constructed ) {
            e.preventDefault();
            e.stopPropagation();
          }
          break;
      }
    }
  };
  IScroll.utils = utils;
  
  if ( typeof module != 'undefined' && module.exports ) {
    module.exports = IScroll;
  } else if ( typeof define == 'function' && define.amd ) {
          define( function () { return IScroll; } );
  } else {
    window.IScroll = IScroll;
  }
  
  })(window, document, Math);
  
/*! card.js v0.0.1 https://github.com/coffeedriven/cardjs/LICENCE */

;(function ( global ) {
    'use strict';

    /*
      card.js v0.0.1
      A JavaScript library for card type detection.
      https://github.com/coffeedriven/cardjs/
      Copyright (c) 2015 Maciej Dzikowicki <mdzikowicki@gmail.com>
      MIT Licence
    */

    var card = function(number) {
      if (typeof number !== 'string') {
        throw new TypeError('cardNumber must be a string!');
      }

      var cardNumber = number.trim().replace(/\s/g, '');

      return new Card(cardNumber);
    };

    card.CARD_TYPES = [
      {type: 'visa', numberRegex: /^4[0-9]{12}(?:[0-9]{3})?$/, iinNumberRegex: /^4/},
      {type: 'mastercard', numberRegex:/^5[1-5][0-9]{14}$/, iinNumberRegex: /^5[1-5]/},
      {type: 'amex', numberRegex:/^3[47][0-9]{13}$/, iinNumberRegex: /^3[47]/},
      {type: 'maestro', numberRegex:/^(?:5018|5020|5038|5612|5893|6304|6759|6761|6762|6763|0604|6390)\d{12}(?:\d\d)?$/, iinNumberRegex: /^(?:5018|5020|5038|5612|5893|6304|6759|6761|6762|6763|0604|6390)/},
      {type: 'diners', numberRegex:/^3(?:0[0-5]|[68][0-9])[0-9]{4,}$/, iinNumberRegex: /^3(?:0[0-5]|[68][0-9])/},
      {type: 'discover', numberRegex:/^6(?:011|5[0-9]{2})[0-9]{12}$/, iinNumberRegex: /^6(?:011|5)/},
      {type: 'jcb', numberRegex:/^(?:2131|1800|35[0-9]{3})[0-9]{3,}$/, iinNumberRegex: /^(?:2131|1800|35[0-9]{2})/},
      {type: 'uatp', numberRegex:/^1[0-9]{14}$/, iinNumberRegex:/^1/},
      {type: 'interpayment', numberRegex:/^(636)\d{13,16}$/, iinNumberRegex:/^(636)/},
      {type: 'instapayment', numberRegex:/^(63[7-9])\d{13}$/, iinNumberRegex:/^(63[7-9])/},
      {type: 'unionpay', numberRegex:/^(62|88)\d{14,17}$/, iinNumberRegex:/^(62|88)/},
      {type: 'dankort', numberRegex:/^(5019)\d{12}$/, iinNumberRegex:/^(5019)/}
    ];

    var Card = function(cardNumber) {
      this._cardNumber = cardNumber;
    };

    Card.prototype.isValid = function() {
      return luhnChk(this._cardNumber);
    };

    var checkType = function(cardNumber, regexType) {
      var cardType = null;
      card.CARD_TYPES.some(function(type) {
        return type[regexType].test(cardNumber) ? (cardType = type, true) : false;
      });
      return !!cardType ? cardType.type : undefined;
    };

    Card.prototype.getType = function() {
      return checkType(this._cardNumber, 'numberRegex');
    };

    Card.prototype.getIINType = function() {
      return checkType(this._cardNumber, 'iinNumberRegex');
    };

    /**
     * Implementation thanks to gist: https://gist.github.com/ShirtlessKirk/2134376
     */
    var luhnChk = (function(arr) {
      return function(ccNum) {
        var
            len = ccNum.length,
            bit = 1,
            sum = 0,
            val;

        while (len) {
          val = parseInt(ccNum.charAt(--len), 10);
          sum += (bit ^= 1) ? arr[val] : val;
        }

        return sum && sum % 10 === 0;
      };
    }([0, 2, 4, 6, 8, 1, 3, 5, 7, 9]));

    // Node and other CommonJS-like environments that support module.exports.
    if (typeof module !== 'undefined' && module.exports) {
      module.exports = card;

      //Browser.
    } else {
      global.card = card;
    }

})( this );

$(document).keydown(function(e) {
  switch(e.which) {
    
    case 37: // left
      $(document).trigger({
        type: 'keyNav',
        key: 'left'
      });
    break;

    case 39: // right
      $(document).trigger({
        type: 'keyNav',
        key: 'right'
      });
    break;

    default: return; // exit this handler for other keys
  }
});

$(document).on('keyNav', function(e) {
  var el = $('[data-click="' + e.key + '"]');
  if ( el.length && !$('input').is(":focus") ) {
    el[0].click();
  }
});

$(document).ready( function(e) {
  window.isMobile = !(breakpoint.mobile_max < window.innerWidth);
} );
$(window).on( 'resize', function(e) {
      
  if ( window.isMobile && breakpoint.mobile_max < window.innerWidth || 
      !window.isMobile && breakpoint.mobile_max >= window.innerWidth ) {

    window.isMobile = !(breakpoint.mobile_max < window.innerWidth);
    $(window).trigger({
      type: 'mobile',
      isMobile: window.isMobile
    });
  }
} );
/*
|--------------------------------------------------------------------------
| Validate Integer
|--------------------------------------------------------------------------
| Helper function to check whether if value is an integer or not
| Input: int
*/
function isInteger( int ) {
  var regex = /^\d+$/;
  return regex.test(int);
}


/*
|--------------------------------------------------------------------------
| Validate Email Address
|--------------------------------------------------------------------------
| Helper function to check whether email is valid or not
| Input: String
*/
function isEmail( email ) {
  var regex = /^([a-zA-Z0-9_.+-])+\@(([a-zA-Z0-9-])+\.)+([a-zA-Z0-9]{2,4})+$/;
  return regex.test(email);
}

RegExp.escape = function(s) {
    return s.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
};
function detectTouch() {
  
  var isTouchDevice = 'ontouchstart' in document.documentElement;
  if ( !isTouchDevice ) {
    $('body').addClass('no-touch');
    $('body').removeClass('touch');
  } else {
    $('body').removeClass('no-touch');
    $('body').addClass('touch');
  }
}
$(document).ready(detectTouch);

// Read a page's GET URL variables and return them as an associative array.
function getUrlVars() {
  var vars = [], hash;
  var hashes = window.location.href.slice(window.location.href.indexOf('?') + 1).split('&');
  for(var i = 0; i < hashes.length; i++) {
    hash = hashes[i].split('=');
    vars.push(hash[0]);
    vars[hash[0]] = hash[1];
  }
  return vars;
}

function getUrlVar( name ) {
  return getUrlVars()[name];
}


/*!
  query-string
  Parse and stringify URL query strings
  https://github.com/sindresorhus/query-string
  by Sindre Sorhus
  MIT License
*/
(function () {
  'use strict';
  var queryString = {};

  queryString.parse = function (str) {
    if (typeof str !== 'string') {
      return {};
    }

    str = str.trim().replace(/^\?/, '');

    if (!str) {
      return {};
    }

    return str.trim().split('&').reduce(function (ret, param) {
      var parts = param.replace(/\+/g, ' ').split('=');
      var key = parts[0];
      var val = parts[1];

      key = decodeURIComponent(key);
      // missing `=` should be `null`:
      // http://w3.org/TR/2012/WD-url-20120524/#collect-url-parameters
      val = val === undefined ? null : decodeURIComponent(val);

      if (!ret.hasOwnProperty(key)) {
        ret[key] = val;
      } else if (Array.isArray(ret[key])) {
        ret[key].push(val);
      } else {
        ret[key] = [ret[key], val];
      }

      return ret;
    }, {});
  };

  queryString.stringify = function (obj) {
    return obj ? Object.keys(obj).map(function (key) {
      var val = obj[key];

      if (Array.isArray(val)) {
        return val.map(function (val2) {
          return encodeURIComponent(key) + '=' + encodeURIComponent(val2);
        }).join('&');
      }

      return encodeURIComponent(key) + '=' + encodeURIComponent(val);
    }).join('&') : '';
  };

  queryString.push = function (key, new_value, replaceState) {
    var params = queryString.parse(location.search);
    params[key] = new_value;
    var new_params_string = queryString.stringify(params);

    if ( replaceState ) {
      history.replaceState({}, "", window.location.pathname + '?' + new_params_string);
    } else {
      history.pushState({}, "", window.location.pathname + '?' + new_params_string);
    }
    
  }
  
  queryString.pushGroup = function ( paramsGroup ) {

    var params = queryString.parse(location.search);
    for (var key in paramsGroup) {
      if (paramsGroup.hasOwnProperty(key)) {
        params[key] = paramsGroup[key];
      }
    }

    var new_params_string = queryString.stringify(params)
    history.pushState({}, "", window.location.pathname + '?' + new_params_string);
  }

  queryString.getVars = function () {
    var vars = [], hash;
    var hashes = window.location.href.slice(window.location.href.indexOf('?') + 1).split('&');
    for ( var i = 0; i < hashes.length; i++ ) {
      hash = hashes[i].split('=');
      vars.push(hash[0]);
      vars[hash[0]] = hash[1];
    }
    return vars;
  }

  queryString.get = function ( name ) {
    return queryString.getVars()[name];
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = queryString;
  } else {
    window.queryString = queryString;
  }
})();


function processInvalid(e) {
  e.preventDefault();
  $(this).addClass('invalid');
  $('.form__error').removeClass('-shown');
  var $form_error = $('.form__error[for="' + $(this).attr('id') + '"]');
  
  if ( $form_error.length ) {
    $form_error.addClass('-shown');
  }

  var form_error = $(this)[0].form.getAttribute('data-form-error');
  var $form_error_el = $('#' + form_error);

  if ( $form_error_el.length ) {
    $form_error_el.addClass('-shown');
    $('html, body').animate({
      scrollTop: $form_error_el.offset().top - Navbar.$el.height()
    }, 100);
  };  
}

// Check fields on "invalid"
$('input').on( 'invalid', processInvalid);
$('textarea').on( 'invalid', processInvalid);

function removeInvalid(e) {
  $(this).removeClass('invalid');
}

$('input').on('focus', removeInvalid);
$('textarea').on('focus', removeInvalid);


$('input.js-file-input').change( function() { 
    var files = this.files;
    var file_list = $('#' + $(this).attr('data-file-list'));
    file_list.empty();
    
    var fileMarkup = '<div class="uk-margin-top uk-flex uk-flex-between">';
    for ( var i = 0; i < files.length; i++ ) {
      fileMarkup += '<span class="uk-margin-right font-regular" id="' + files[i].name + '">' + files[i].name + '</span>';
      fileMarkup += '<a href="#" class="js-remove-file link -nocolor -underline " data-targt-file="' + files[i].name + '">' + wp_vars.strings.fileupload_removefile_string + '</span>';
      fileMarkup += '</div>';
      file_list.append( fileMarkup );
      fileMarkup = '';
    }
});

$( document ).on('click', '.js-remove-file' , function(e) {
  e.preventDefault();
  var file_list_container = $(this).parent().parent();
  var input = $('#' + file_list_container.attr('data-input'));
  file_list_container.empty();
  input.val("");
});

var LotsSearch = {
  $form   : $('#lotsearch-form'),
  $input  : $('#lotsearch-input'),
  $error  : $('.form__error[for="lotsearch-input"]'),
  exists  : $('#lotsearch-form').length,
  isValid: function( value, min, max, present) {
    return isInteger( value ) && value >= min && value <= max;
  }
};

if ( LotsSearch.exists ) {

  LotsSearch.$form.submit(function(e) {
    
    var min     = 1;
    var max     = parseInt(LotsSearch.$input.attr('data-max'));
    var chosen  = parseInt(LotsSearch.$input.val());
    var present = parseInt(LotsSearch.$input.attr('data-present'));

    if ( !LotsSearch.isValid( chosen, min, max, present ) )  {
      e.preventDefault();
      LotsSearch.$error.show();
    }
  });
  
  // Hide error message on input
  LotsSearch.$input.on( 'input', function(e) {    
    LotsSearch.$error.hide();
  });

  // Disable Mouse scrolling
  LotsSearch.$input.on('mousewheel',function(e){ $(this).blur(); });
  // Disable keyboard scrolling
  LotsSearch.$input.on('keydown',function(e) {
    var key = e.charCode || e.keyCode;
    // Disable Up and Down Arrows on Keyboard
    if( 38 == key || 40 == key ) {
      e.preventDefault();
    } else {
      return;
    }
  });
  
  LotsSearch.$form.click(function(e) {    
    LotsSearch.$error.hide();
  });
  
}

$(document).ready(function() {
  
  $('.js-mask-order-lot-value').mask('#.##0', {reverse: true});

  $('.js-clone-value').on('input', function (e) {
    var clones = $(this).attr('data-clone-destiny');
    var clean_value = $(this).cleanVal();
    $(clones).val(clean_value);
  });

});

var NewsletterForm = {};

NewsletterForm.$form = $('#newsletter-form');
NewsletterForm.$form_area = $('#newsletter-form-area');
NewsletterForm.$inputs = $('.js-newsletter-input');

NewsletterForm.$name_input = $('#newsletter-name');
NewsletterForm.$email_input = $('#newsletter-email');

NewsletterForm.$newsletter_compliance = $('#newsletter-compliance');

/*
Check if fields are filled and email is valid.
Show error if conditions are not met
*/
NewsletterForm.validate = function(name, email) {
  
  var name = NewsletterForm.$name_input.val();
  var email = NewsletterForm.$email_input.val();
  
  if ( 2 < name.length ) {
    $('.input__error[for=newsletter-name]').removeClass('-shown');
  } else {
    $('.input__error[for=newsletter-name]').addClass('-shown');
  }
  if ( isEmail(email) ) {
    $('.input__error[for=newsletter-email]').removeClass('-shown');
  } else {
    $('.input__error[for=newsletter-email]').addClass('-shown');
  }
  
  return isEmail(email) && name.length > 2;
};

NewsletterForm.submit = function(name, email, $form){
  
  var host = window.location.port ? window.location.hostname + ':' + window.location.port : window.location.hostname;
  var form_id = $form.attr('data-gform-id');
  var url = window.location.protocol + '//' + host + '/gravityformsapi/forms/' + form_id +  '/submissions';
  
  var data = {
    input_values: {  
      input_1: name,
      input_2: email
    }
  };

  $.ajax({
    url: url,
    type: 'POST',
    data: JSON.stringify(data)
  }).done(function (data, textStatus, xhr) {
    var response = JSON.stringify(data.response, null, '\t');
  });


  var newsletter_offset = $('#newsletter-area').offset();
  if ( $(document).scrollTop() > newsletter_offset.top ) {
    $('html, body').animate({
      scrollTop: newsletter_offset.top - Navbar.$el.height(),
    }, 250);
  }

};

NewsletterForm.$form.on('submit', function(e) {
  // 'Required' does not work in Safari
  // it is necesary to preventDefaul() if the fields are not validated  
  e.preventDefault();

  if ( NewsletterForm.validate() && NewsletterForm.$name_input[0].checkValidity() && NewsletterForm.$email_input[0].checkValidity() ) {
    
    NewsletterForm.submit(NewsletterForm.$name_input.val(), NewsletterForm.$email_input.val(), $(this));
    
    $('#newsletter-form-area').addClass('uk-animation-fade uk-animation-reverse')
                              .addClass('uk-hidden');
    
    $('#newsletter-success').addClass('uk-animation-fade')
                            .removeClass('uk-hidden');
  }
});

/**
 * Remove warning message on click
 */
NewsletterForm.$inputs.on('click', function(e) {
  $('.input__error[for=' + $(this).attr('id') + ']').removeClass('-shown');
});
NewsletterForm.$inputs.on('focus', function(e) {
  $('.input__error[for=' + $(this).attr('id') + ']').removeClass('-shown');
});
NewsletterForm.$inputs.on('input', function(e) {
  
  if ( NewsletterForm.$name_input.val() && NewsletterForm.$email_input.val() ) {
    NewsletterForm.$newsletter_compliance.fadeIn(250, false);
  } else {
    NewsletterForm.$newsletter_compliance.fadeOut(250, false);
  }
});

// Check fields on "invalid"
NewsletterForm.$inputs.on('invalid', function(e) {
  e.preventDefault();
  NewsletterForm.validate();
});

/**
 * Enables permanent floating placeholder on HTML forms by adding padding to the input, 
 * moving the cursor to the position right after the placeholder.
 * 
 * Example:
 *  ________________________
 * |                       |
 * | NAME: Luís            |
 * |_______________________|
 * NAME: - Fixed placeholder
 * Luís - Text introduced by user
 * 
 */
function stylePlaceholders($placeholders) {

  if( !$placeholders.length ) return;

  var elWidth = 0;
  var placeholder_offset = 0;
  var input_padding = 0;

  $placeholders.each( function(i, el) {
    var $placeholder = $placeholders.eq(i);
    var placeholder_for_attr = $placeholder.attr('for');
    var $placeholder_for = $('#' + placeholder_for_attr);

    if ( $placeholder.hasClass('-textarea') || $placeholder.siblings('.ginput_container').children('.textarea').length )  {
      elHeight = Math.round($placeholder.height()) + 2;
      placeholder_offset = parseInt($placeholder.css('top'));
      $placeholder_for.css({ 'padding-top': elHeight + placeholder_offset});
      return;
    }

    elWidth = Math.round($placeholder.width());
    placeholder_offset = parseInt($placeholder.css('left'));
    placeholder_parent_offset = parseInt($placeholder.parent().css('padding-left'));

    input_padding = elWidth + ( placeholder_offset - placeholder_parent_offset ) * 1.75;
    
    if ( $placeholder_for.hasClass('js-single-select') ) {
      var $select_container = $('#' + 'select2-' + placeholder_for_attr + '-container');
      $select_container.css({ 'padding-left': input_padding });

      if ( $select_container.attr('title') ) {
        $placeholder.addClass('-focus');
      }
    } else if ( $placeholder_for.hasClass('js-multiple-select') ) {
      $('#' + placeholder_for_attr + ' + ' + '.select2 input[type="search"]').css({ 'padding-left': input_padding });
    } else {
      $placeholder_for.css({ 'padding-left': input_padding });
    }
    
  });


}

$(document).ready(function() {
  setTimeout(function() {
    stylePlaceholders( $('label.input__placeholder') );
    stylePlaceholders( $('label.gfield_label') );
  }, 350);

});


/**
 * Changes palceholder opacity based on input value
 * Has content: add -focus
 * No content: remove -focus
 */
function controlPlaceholder(e) {
  
  var $target_placeholder = $('label[for="'+e.target.id+'"]');
  if( !$target_placeholder.length ) return;

  if( ($(this).val() && $(this).val().length) || 'focus'  === e.type || 'click'  === e.type ) {
    $target_placeholder.addClass('-focus -focused');
  } else {
    $target_placeholder.removeClass('-focus');
  }
}
$(document).ready(function() {
  var $placeholders = $('.input__placeholder');
  $placeholders.each( function(i, el) {
    var $placeholder = $placeholders.eq(i);
    var $input = $('#' + $placeholder.attr('for') );
    if( $input.val() ) $input.trigger('input');
  });
});
$('input, textarea, select').on('input', controlPlaceholder);
$('input, textarea, select').on('focus', controlPlaceholder);
$('input, textarea, select').on('blur', controlPlaceholder);
$('.js-multiple-select, .js-single-select').on('change', controlPlaceholder);
$('.js-multiple-select, .js-single-select').on('select2:open', controlPlaceholder);
$('.js-multiple-select, .js-single-select').on('select2:close', controlPlaceholder);
$('.js-multiple-select, .js-single-select').on('select2:select', controlPlaceholder);
$('.js-multiple-select, .js-single-select').on('select2:unselect', controlPlaceholder);

// Initialize Swiper
var slider_full_conf = {
  loop: true,
  nextButton: ".swiper-button-next",
  prevButton: ".swiper-button-prev",
  autoplay: 6000,
  autoplayDisableOnInteraction: false,
  effect: "fade",
  speed: 750,
};
var slider_full = new Swiper(".full-slider.swiper-container", slider_full_conf);

$(document).ready(function () {
  if (!$(".full-slider").length) return;
  $(".full-slider").find(".js-full-slider-slowload").show();

  $mobile_sliders = $(".swiper-slide.mobile:not(.swiper-slide-duplicate)");
  $desktop_sliders = $(".swiper-slide.desktop:not(.swiper-slide-duplicate)");

  function loadSlides() {
    if (window.innerWidth < 1199) {
      slider_full.removeAllSlides();

      for (i = 0; i < $mobile_sliders.length; i++) {
        $slide = $mobile_sliders.filter(`[data-index="${i}"]`);
        slider_full.appendSlide($slide);
      }

      slider_full.slideTo(1);
    } else {
      slider_full.removeAllSlides();

      for (i = 0; i < $desktop_sliders.length; i++) {
        $slide = $desktop_sliders.filter(`[data-index="${i}"]`);
        slider_full.appendSlide($slide);
      }

      slider_full.slideTo(1);
    }
  }

  loadSlides();

  $(window).on("resize", function () {
    if (window.innerWidth > 1200) {
      loadSlides();
    }
  });
});

var SliderItunes = {};

SliderItunes.$el = null;

SliderItunes.conf = {

  slidesPerView : 'auto',

  mousewheelControl : true,
  centeredSlides : true,
  grabCursor : true,
  slideToClickedSlide : true,
  virtualTranslate : false,
  keyboardControl : true,
  preloadImages : false,

  lazyLoading : false,
  lazyLoadingInPrevNext : true,
  lazyLoadingInPrevNextAmount : 15,

  freeMode : true,
  freeModeSticky : true,
  freeModeMomentumRatio : 0.25,
  freeModeMomentumVelocityRatio : 2,

  speed : 400,
  effect : 'itunes',
  itunes : {
    stretch : 0,
    depth : 235,
    modifier : 0.85,
    scaleMultiplier : 0.001,
    scaleOffset : 1
  },
  spaceBetween : -155,
  breakpoints : {
    // window width <= 1199
    1199 : {
      spaceBetween : -120
    }
  }
};

SliderItunes.mobileConf = {
  centeredSlides : true,
  grabCursor : true,

  freeMode : true,
  freeModeMomentum: true,
  freeModeMomentumRatio : 0.3,
  freeModeMomentumVelocityRatio : 1.5,
  freeModeMomentumBounce: false,
  freeModeMinimumVelocity: 0,
  freeModeSticky : true,
  freeModeMomentumMinimumVelocity : 0.3,
  freeModeMomentumMaximumVelocity : 0.9,
  
  scrollbarHide : false,
  slideToClickedSlide : true,
  slidesPerView : 'auto',
  spaceBetween : 15,
  speed : 300,

  preventClicks : true,
  preventClicksPropagation : true
};

SliderItunes.resetSlider = function() {
  this.$el[0].swiper.destroy(false, true);
  this.setup();
};

SliderItunes.setup = function() {

  if ( !this.$el.length ) return;

  var slider_conf = {};
  if ( breakpoint.mobile_max >= window.innerWidth ) {
    slider_conf = this.mobileConf;
  } else {
    slider_conf = this.conf;
  }

  return new Swiper(this.$el, slider_conf);
};

SliderItunes.init = function(el) {
  this.$el = $(el);

  if ( !this.$el.length ) return;
  
  this.setup();
  
  $(window).on('mobile', function(e) {
    SliderItunes.resetSlider();
  });
};

$(document).ready(function() {
  SliderItunes.init('.js-slider-itunes');
});

var StepsSlider = {};
StepsSlider.$el = $('.js-steps-list-slider');

StepsSlider.icons_slider = null;
StepsSlider.steps_slider = null;

StepsSlider.steps_slider_conf = {
  preventClicks: true,
  preventClicksPropagation: false,
  slidesPerView: 1,
  spaceBetween: 25,
  autoHeight: true,
  onTouchMove: function (s, e) {
    StepsSlider.icons_slider.wrapper.transform('translate3d(' + StepsSlider.calcIconsTranslate(s.translate) + 'px, 0px, 0px)');
  },
  onSlideChangeStart: function (s) {
    StepsSlider.icons_slider.wrapper.transform('translate3d(-' + 0.5 * StepsSlider.icons_slider.activeIndex * StepsSlider.icons_slider.container.width() + 'px, 0px, 0px)');
  }
};

StepsSlider.icons_slider_conf = {
  centeredSlides: true,
  grabCursor: true,
  spaceBetween: 0,
  slidesPerView: 1,
  slideToClickedSlide: true,
  virtualTranslate: true,
  width: window.innerWidth / 2,
  onTouchMove: function (s, e) {
    s.wrapper.transform('translate3d(' + StepsSlider.calcIconsTranslate(StepsSlider.steps_slider.translate) + 'px, 0px, 0px)');
  },
  onSlideChangeStart: function (s) {
    s.wrapper.transform('translate3d(-' + 0.5 * s.activeIndex * s.container.width() + 'px, 0px, 0px)');
  }
};

StepsSlider.calcIconsTranslate = function (steps_translate) {
  //linear fit {0,0},{-575, -295},{-1150, -590}
  return Math.round(0.513043 * steps_translate);
};

StepsSlider.init = function () {

  if (!StepsSlider.$el.length) return;

  var steps_slider = new Swiper(StepsSlider.$el.data('steps-slider'), StepsSlider.steps_slider_conf);
  var icons_slider = new Swiper(StepsSlider.$el.data('icons-slider'), StepsSlider.icons_slider_conf);

  if ($(StepsSlider.$el.attr('data-icons-slider')).data('disable-touch')) {
    steps_slider.disableTouchControl();
  }

  steps_slider.params.control = icons_slider;
  icons_slider.params.control = steps_slider;

  StepsSlider.icons_slider = icons_slider;
  StepsSlider.steps_slider = steps_slider;

  StepsSlider.$el.addClass('slider-active');
  StepsSlider.manage();
};

StepsSlider.manage = function () {

  if (!StepsSlider.$el.length) return;
  StepsSlider.icons_slider.wrapper.transform('translate3d(-' + 0.5 * StepsSlider.icons_slider.activeIndex * StepsSlider.icons_slider.container.width() + 'px, 0px, 0px)');

  if (breakpoint.tablet <= window.innerWidth && (StepsSlider.$el.hasClass('slider-active') || StepsSlider.$el.hasClass('-show-all-on-tablet'))) {

    StepsSlider.icons_slider.destroy(false, true);
    StepsSlider.steps_slider.destroy(false, true);
    StepsSlider.$el.removeClass('slider-active');
  } else if (breakpoint.tablet_max >= window.innerWidth && !StepsSlider.$el.hasClass('slider-active')) {

    StepsSlider.icons_slider.init();
    StepsSlider.steps_slider.init();
    StepsSlider.$el.addClass('slider-active');
  }
};

$(document).ready(StepsSlider.init)
$(window).on('resize', StepsSlider.manage);

$(document).ready( function(e) {
  var menu_item = $('li[class*="js-activate-menu-parent-"]');

  if ( !menu_item.length ) return;
  menu_item.parent().parent().parent().addClass('-active -active-parent');
});
var LotsCounter = {
  el: $('.js-added-lots-count'),

  currentValue: function() {
    return parseInt($('.js-added-lots-count').html());;
  },
  addLot: function() {
    var value = LotsCounter.currentValue();
    value++;
    LotsCounter.updateValue(value);
  },
  removeLot: function() {
    var value = LotsCounter.currentValue();
    value--;
    LotsCounter.updateValue(value);
  },
  updateValue: function(value) {

    var counters = $('.js-added-lots-count');
    counters.each( function(i, el) {
      var counter = counters.eq(i);
      counter.html(value);

      if ( !counter.hasClass('-nohide') ) {
        if ( 0 < value ) {
          counter.removeClass('hidden');
        } else {
          counter.addClass('hidden');
        }
      }
    });
    
  },
  
  init: function(){
    
    // Unsubmitted Orders menu item
    var $unsubmitted_orders_menu_items = $('.js-added-lots-menu-count');
    if ( !$unsubmitted_orders_menu_items.length ) return;

    $unsubmitted_orders_menu_items.each( function(i, el) {
      var $unsubmitted_orders_menu_item = $unsubmitted_orders_menu_items.eq(i);
      var count = wp_vars.orders.unsubmitted_lots;

      var el_classes = 'added-lots-icon js-added-lots-count';

      if ( 0 >= count ) {
        el_classes += ' hidden';
      }

      if ( $unsubmitted_orders_menu_item.attr('data-parent') ) {
        $unsubmitted_orders_menu_item.children('a').append('<span class="' + el_classes + '">' + count + '</span>');
        // Orders dropdown
        var $orders_dropdown = $unsubmitted_orders_menu_item.parent().parent().parent();
        // Myveritas menu item
        var $myveritas_dropdown = $orders_dropdown.parent().parent().parent();

        $orders_dropdown.children('a').append('<span class="' + el_classes + '">' + count + '</span>');
        $myveritas_dropdown.append('<span class="' + el_classes + ' uk-position-center-right">' + count + '</span>');
      }
    });
  }
}

$(window).ready( function(e) {
  
  $('.js-available-soon').on('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    $('.js-open-available-soon-modal').click();
    UIkit.toggle('#available-soon-modal').toggle();
  });
});
// Breakpoints
var breakpoint = {
  small: 640,
  medium: 768,
  large: 1200,
  xlarge: 1440,
};

breakpoint.small_max = breakpoint.medium - 1;
breakpoint.medium_max = breakpoint.large - 1;
breakpoint.large_max = breakpoint.xlarge - 1;

// Mobile
breakpoint.mobile_max = breakpoint.medium_max;

// Phone
breakpoint.phone_max = breakpoint.small_max;

// Tablet
breakpoint.tablet = breakpoint.medium;
breakpoint.tablet_max = breakpoint.medium_max;
$(document).ready( function() {
  if ( !$('.js-card-auction-list').length ) return;
  new Swiper('.js-card-auction-list', {
    slidesPerView   : 'auto',
    spaceBetween    : 15,
    grabCursor      : true,
    freeMode        : true,
    freeModeSticky  : true,
    freeModeMomentumVelocityRatio : 3
  });
} );

$(document).ready( function() {

  $(document).on('click', '.js-remove-order-lot', function(e) {
    e.preventDefault();
    Cursor.load();
    
    var _data = {
      'nonce'     : wp_vars.ajax_nonce,
      'action'    : 'remove-lot',
      'lot-id'    : $(this).attr('data-lot-id'),
      'order-id'  : $(this).attr('data-order-id') 
    };
    var _url = wp_vars.ajax_routes.order_update;

    $.ajax({
      url: _url,
      dataType: 'json',
      type: 'POST',
      data: _data,
      success: function (response, textStatus, httpRequest) {

        Cursor.default();
        if ( 'success' === response.result ) {
          var $lot_remover = $('.js-remove-order-lot[data-lot-id="' + response.lot.id + '"][data-order-id="' + response.lot.order + '"]');
          var $lot_display = $('#' + $lot_remover.attr('data-target-lot'));
          LotsCounter.removeLot();
          
          if ( response.order_canceled ) {
            window.location = wp_vars.pages.myveritas.orders_unsubmitted;
          } else {
            location.reload();
          }
        }
      }
    });
  });

  $('.js-remove-order-lot-checkbox').change( function(e) {

    var $target_lot = $('#' + $(this).attr('data-target-lot'));
    var lot_id = $(this).attr('data-lot-id');
    var $revert_button = $('#' + lot_id + '-revert-button');
    var $remove_button = $('#' + lot_id + '-remove-button');

    if ( $(this)[0].checked) {
      $target_lot.addClass('-remove');
      $revert_button.removeClass('hidden');
      $remove_button.addClass('hidden');
    } else {
      $target_lot.removeClass('-remove');
      $revert_button.addClass('hidden');
      $remove_button.removeClass('hidden');
    }
    
    if ( !$('.js-remove-order-lot').length &&
         $('.js-remove-order-lot-checkbox').length === $('.js-remove-order-lot-checkbox:checked').length ) {
      UIkit.modal('#remove-all-lots-modal').show();
    }
  } );
    
} );

// Remover Order Action
$(document).on('click', '.js-remove-order', function(e) {
  e.preventDefault();
  
  var order_id = $(this).attr('data-order-id');

  var _data = {
    'nonce'     : wp_vars.ajax_nonce,
    'action'    : 'remove-order',
    'order-id'  : order_id
  };
  var _url = wp_vars.ajax_routes.order_update;

  Cursor.load();
  $.ajax({
    type: 'post',
    dataType: 'json',
    url: _url,
    data: _data,
    success: function (response, textStatus, httpRequest) {
      if ( 'success' === response.result ) {

        if ( $('body').hasClass('myveritas_orders_submitted') || $('body').hasClass('myveritas_orders_unsubmitted') ) {
          location.reload();
        }

        if ( $('body').hasClass('myveritas_order_edit') ) {
          window.location = wp_vars.pages.myveritas.orders_unsubmitted;
        }

        if ( $('body').hasClass('myveritas_order') ) {
          window.location = wp_vars.pages.myveritas.orders_submitted;
        }
        
      }
      Cursor.default();
    },
    error: function (jqXHR, textStatus, errorThrown) {
      Cursor.default();
    }
  });
});

// Cookie Bar display
$(document).ready(function() {
  $('.cookie-notice').cookieBar({ closeButton : '.cookie-notice-close' });
  $('.cookie-notice').removeClass('hidden');
});
$(window).on( 'load', function() {

  if ( $('.js-card-number').length ) {
    var card_number = $('.js-card-number')[0].value;  
    var card_type_field = '#' + $('.js-card-number').attr('data-card-type');
    var card_type = card(card_number).getType();

    if ( card_type ) {
      $(card_type_field).addClass('-icon-' + card_type);
      $(card_type_field).removeClass('hidden');
    }
  }

  $('.js-card-number').on('input', function(e) {
    var card_number = this.value;
    var card_type_field = '#' + $(this).attr('data-card-type');
    if ( !card_number ) {
      $(card_type_field).addClass('hidden');
      return;
    }
    var card_type = card(card_number).getType();
    if ( card_type ) {
      $('.form__error[for="' + $(this).attr('id') + '"]').hide();
      $(card_type_field).addClass('-icon-' + card_type);
      $(card_type_field).removeClass('hidden');
    } else {
      $(card_type_field).removeClass().addClass('credit-card-icon -form-display');  
    }

  });

  // Hide file display on 'remove'
  $('.js-remove-credit-card').change( function() {
    var card_fields   = '#' + $(this).attr('data-card-fields');
    var card_display  = '#' + $(this).attr('data-card-display');
    
    $(card_display).fadeOut(200, function(){
      var card_inputs = $(card_fields + ' ' + '.js-card-field')
      card_inputs.val('');
      $(card_fields).removeClass('hidden');
    });
  });

});
var Cursor = {};

Cursor.load = function() {
  $("body").css("cursor", "progress");
};
Cursor.default = function() {
  $("body").css("cursor", "default");
};

// Custom Select boxes

$(document).ready(function() {
  $('.js-single-select').select2({
    placeholder: ''
  });

  /**
   * Match only strings that beggin or have a 
   * word starting with the term given by the user
   * 
   * @param {String} term 
   * @param {String} text 
   */
  function matchWords ( term, text ) {
    var pattern = new RegExp("(^|\\s)" + term + ".*", 'gi');
    var pattern_middle = new RegExp("\\s" + RegExp.escape(term) + ".*", 'gi');
    
    return pattern.test(text);
  }

  $.fn.select2.amd.require(['select2/compat/matcher'], function (oldMatcher) {
    $('.js-multiple-select').select2({
      matcher: oldMatcher(matchWords),
      tags: true,
      tokenSeparators: [',', ';'],
      allowClear: false,
    })
  });

  // Hide dropdown
  $('.js-multiple-select').on("select2:open", function (e) { 
    $('.select2-dropdown').hide();
  });

  $(document).on('input', '.select2-selection--multiple .select2-search__field', function(e) {
    
    if ( e.target.value ) {
      $('.select2-dropdown').show();
    } else {
      $('.select2-dropdown').hide();
    }

  });
  
});

    

$(document).on('click', '.js-disable-link', function(e) {
  e.preventDefault();
});

$(document).ready( function(){

  // No Web Storage support
  if ( typeof(Storage) === "undefined" ) {
    return;
  }

  // Clean localstorage when it is not needed
  if ( !$('.js-favorite-lot').length && window.refreshed ) {  
    localStorage.setItem('favorite_lots', null);
  }

  // Return if page was refreshed
  if ( window.refreshed ) {
    return;
  }
  
  var favorite_lots = JSON.parse(localStorage.getItem('favorite_lots'));
  favorite_lots = favorite_lots ? favorite_lots : [];

  var lot_id, 
      is_favorite,
      $favorite_icon;
  for ( var i = 0; i < favorite_lots.length; i++ ) {
    lot_id = favorite_lots[i].value;
    is_favorite = favorite_lots[i].data;
    
    $favorite_icon = $('.js-favorite-lot[data-lot-id="' + lot_id + '"]');
    if ( $favorite_icon.length ) {
      $favorite_icon.children('.checkbox')[0].checked = is_favorite;
    }
  }

} );

$(document).on('click', '.js-favorite-lot', function(e) {
  e.preventDefault();
  
  var is_loggedin = $('body').attr('data-client-loggedin');
  if ( !is_loggedin ) return;

  var _data = {
    'action': $(this).children('.checkbox')[0].checked ? 'remove' : 'add',
    'nonce' : wp_vars.ajax_nonce,
    'lot-id': $(this).attr('data-lot-id')
  }

  $.ajax({
    url: wp_vars.ajax_routes.favorites_update,
    dataType: 'json',
    type: 'POST',
    data: _data,
    success: function (data, textStatus, httpRequest) {

      if ( 'success' === data.result ) {
        
        var is_favorite = 'add' ===  data.action;
        var $fav_icon = $('.js-favorite-lot[data-lot-id="' + data.lot.id + '"]');
        $fav_icon.find('.checkbox')[0].checked = is_favorite;


        // No Web Storage support
        if ( typeof(Storage) === "undefined" ) {
          return;
        }
        var favorite_lots = JSON.parse(localStorage.getItem('favorite_lots'));
        favorite_lots = favorite_lots ? favorite_lots : [];

        var updated = false;
        for ( var i = 0; i < favorite_lots.length; i++ ) {
          if ( favorite_lots[i].value == data.lot.id ) {
            updated = true;
            favorite_lots[i].data = is_favorite;
            break;
          }
        }
        if ( !updated ) {
          favorite_lots.push({
            value: data.lot.id,
            data: is_favorite
          });
        }
        localStorage.setItem('favorite_lots', JSON.stringify(favorite_lots));

      }
    }
  });

});

$(document).on('mousedown', '.js-favorite-lot', function(e) {
  $(this).addClass('-pressed');
});

$(document).on('mouseup', '.js-favorite-lot', function(e) {
  var el = $(this);
  setTimeout(function() {
    el.removeClass('-pressed');  
  }, 70);
});

$(document).on('click', '.js-remove-favorite', function(e) {
  e.preventDefault();
  
  var _data = {
    'action': 'remove',
    'nonce' : wp_vars.ajax_nonce,
    'lot-id': $(this).attr('data-lot-id')
  }

  $.ajax({
    url: wp_vars.ajax_routes.favorites_update,
    dataType: 'json',
    type: 'POST',
    data: _data,
    success: function (data, textStatus, httpRequest) {
      if ( 'success' === data.result ) {
        var lot_remover = $('.js-remove-favorite[data-lot-id="' + data.lot.id + '"]');
        var lot_display = $('#' + lot_remover.attr('data-target-lot'));
        lot_display.fadeOut(200, function() {
          $(this).remove();
        });

        // No Web Storage support
        if ( typeof(Storage) === "undefined" ) {
          return;
        }
        var favorite_lots = JSON.parse(localStorage.getItem('favorite_lots'));
        favorite_lots = favorite_lots ? favorite_lots : [];

        for ( var i = 0; i < favorite_lots.length; i++ ) {
          if ( favorite_lots[i].value == data.lot.id ) {
            favorite_lots[i].data = false;
            break;
          }
        }
        localStorage.setItem('favorite_lots', JSON.stringify(favorite_lots));
        
      }
    }
  });

});

/**
 * 
 * Enable show/hide behaviour on elements 
 * targeted by checkboxes and radio buttons.
 * 
 * Ex: Show/Hide div on checkbox Check/Uncheck
 * 
 */

$(window).on( 'load', function() {

  var switcher = {
    dom: $('input.switcher'),
    exists : $('input.switcher').length,
    toggle: function( sw ) {
      
      var type = sw.attr('type');
      if( /^(radio|checkbox)$/.test(type) ) {
        sw.each(function (i, el) {
          var target = $(sw.eq(i).attr('data-target'));
          ( !el.checked ) ? target.addClass('hidden') : target.removeClass('hidden');          
        });
      }
    }
  }

  if( switcher.exists ) {
    switcher.toggle( switcher.dom );
    switcher.dom.change( function(e) {
      switcher.toggle( switcher.dom );
    });
  }
});

/**
 * 
 * Enable accordion toggle behaviour when link to 
 * accordion element is pressed.
 * 
 */

$(document).ready(function() {
  
  var hash = window.location.hash;
  if ( hash && '#' !== hash ) {
    
    var $tab = $(hash);
    if ( !$tab.hasClass('js-accordion-tab') ) return;

    $('html, body').animate({
      scrollTop: $tab.offset().top - 60,
    }, 500);
    
    UIkit.accordion($('.js-faq-accordion')).toggle($tab.attr('data-accordion-index'), true);
  }
  

  $('a').on('click', function(e) {
    
    if ( !$('.js-accordion-section').length ) return;

    var target = '#' + this.hash.substr(1);
    
    if ( '#' === target ) return;
    var $tab = $(target);

    if ( !$tab.length || !$tab.hasClass('js-accordion-tab') ) return;
    e.preventDefault();

    var $open_tab = $('.uk-open');
    if ( $open_tab.length ) {
      $open_tab.children('.uk-accordion-content').attr('hidden', 'hidden');
      $open_tab.removeClass('uk-open');
    }
    
    $('html, body').animate({
      scrollTop: $tab.offset().top - 60,
    }, 500);
    
    
    UIkit.accordion($('.js-faq-accordion')).toggle($tab.attr('data-accordion-index'), true);

  });

});

function initMap() {
  
  var map_el = $('.js-map-frame');
  
  if ( !map_el.length ) return;

  var map_location = {
    lat: parseFloat(map_el.attr('data-lat')),
    lng: parseFloat(map_el.attr('data-lng')),
  };  

  var map_style = [
    {
      "elementType": "geometry",
      "stylers": [
        {
          "color": "#f5f5f5"
        }
      ]
    },
    {
      "elementType": "labels.icon",
      "stylers": [
        {
          "visibility": "off"
        }
      ]
    },
    {
      "elementType": "labels.text.fill",
      "stylers": [
        {
          "color": "#616161"
        }
      ]
    },
    {
      "elementType": "labels.text.stroke",
      "stylers": [
        {
          "color": "#f5f5f5"
        }
      ]
    },
    {
      "featureType": "administrative.land_parcel",
      "elementType": "labels.text.fill",
      "stylers": [
        {
          "color": "#bdbdbd"
        }
      ]
    },
    {
      "featureType": "poi",
      "elementType": "geometry",
      "stylers": [
        {
          "color": "#eeeeee"
        }
      ]
    },
    {
      "featureType": "poi",
      "elementType": "labels.text.fill",
      "stylers": [
        {
          "color": "#757575"
        }
      ]
    },
    {
      "featureType": "poi.park",
      "elementType": "geometry",
      "stylers": [
        {
          "color": "#e5e5e5"
        }
      ]
    },
    {
      "featureType": "poi.park",
      "elementType": "labels.text.fill",
      "stylers": [
        {
          "color": "#9e9e9e"
        }
      ]
    },
    {
      "featureType": "road",
      "elementType": "geometry",
      "stylers": [
        {
          "color": "#ffffff"
        }
      ]
    },
    {
      "featureType": "road.arterial",
      "elementType": "labels.text.fill",
      "stylers": [
        {
          "color": "#757575"
        }
      ]
    },
    {
      "featureType": "road.highway",
      "elementType": "geometry",
      "stylers": [
        {
          "color": "#dadada"
        }
      ]
    },
    {
      "featureType": "road.highway",
      "elementType": "labels.text.fill",
      "stylers": [
        {
          "color": "#616161"
        }
      ]
    },
    {
      "featureType": "road.local",
      "elementType": "labels.text.fill",
      "stylers": [
        {
          "color": "#9e9e9e"
        }
      ]
    },
    {
      "featureType": "transit.line",
      "elementType": "geometry",
      "stylers": [
        {
          "color": "#e5e5e5"
        }
      ]
    },
    {
      "featureType": "transit.station",
      "elementType": "geometry",
      "stylers": [
        {
          "color": "#eeeeee"
        }
      ]
    },
    {
      "featureType": "water",
      "elementType": "geometry",
      "stylers": [
        {
          "color": "#c9c9c9"
        }
      ]
    },
    {
      "featureType": "water",
      "elementType": "labels.text.fill",
      "stylers": [
        {
          "color": "#9e9e9e"
        }
      ]
    }
  ];

  var map = new google.maps.Map(map_el[0], {
    center: map_location,
    zoom: 15,
    disableDefaultUI: true,
    draggable: false, 
    zoomControl: false, 
    scrollwheel: false, 
    disableDoubleClickZoom: true,
    styles: map_style,

  });

  var map_overlay = new google.maps.Polygon({
    path: [
      new google.maps.LatLng(-85.1054596961173, -180),
      new google.maps.LatLng(85.1054596961173, 180),
      new google.maps.LatLng(85.1054596961173, 180),
      new google.maps.LatLng(-85.1054596961173, 0)
    ],
    strokeColor: "#00000",
    strokeOpacity: 0,
    strokeWeight: 0,
    fillColor: "#000000",
    fillOpacity: 0.15
  });
  map_overlay.setMap(map);

  if ( breakpoint.mobile_max >= window.innerWidth ) {
    var marker_svg = '<svg width="25px" height="43px" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44.71 76.42"><path fill="#fff" d="M22.82,76.42S74.73-3.4,18.67.11C18.67.11-26,1,22.82,76.42Z"/><circle fill="#898d96" cx="23.01" cy="14.86" r="6.33"/></svg>';
  } else {
    var marker_svg = '<svg width="29px" height="50px" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44.71 76.42"><path fill="#fff" d="M22.82,76.42S74.73-3.4,18.67.11C18.67.11-26,1,22.82,76.42Z"/><circle fill="#898d96" cx="23.01" cy="14.86" r="6.33"/></svg>';
  } 

  var marker = new google.maps.Marker({
    position: map_location,
    map: map,
    icon: { url: 'data:image/svg+xml;charset=UTF-8;base64,' + btoa(marker_svg) }
  });
  
}

var Navbar = {};

Navbar.$el = $('#site-navbar');

Navbar.init = function () {

  Navbar.manage();

  $('.js-navbar-link[href="#"]').on('click', function (e) {
    e.preventDefault();
  });

  $('#site-navbar-hamburguer').on('click', function (e) {
    e.preventDefault();

    Navbar.$el.toggleClass('mobile-open');
    $('html').toggleClass('uk-overflow-hidden');
    Navbar.$el.removeClass('uk-animation-slide-top');
  });

  $(window).on('mobile', function (e) {
    if (Navbar.$el.hasClass('mobile-open')) {
      if (!e.isMobile) {
        $('html').removeClass('uk-overflow-hidden');
      } else {
        $('html').addClass('uk-overflow-hidden');
      }
    }
  });

  $('.js-searchform-toggle').on('click', function (e) {
    e.preventDefault();
    if (breakpoint.mobile_max < window.innerWidth) {
      UIkit.modal('#searchform-modal').show();
    } else {
      var $mobile_search_form = $('#' + $(this).attr('data-form-container'));
      if ($mobile_search_form.toggleClass('-open').hasClass('-open')) {
        $mobile_search_form.find('input').focus();
      }
    }
  });

  $('.js-close-searchform-input').on('click', function (e) {
    e.preventDefault();
    $('.js-site-navbar-searchform').removeClass('-open');
  });

};

Navbar.manage = function () {

  if ($('.js-page-hero').length) {

    if ($(document).scrollTop() >= $('.js-page-hero').height()) {
      Navbar.$el.addClass('-fixed uk-animation-slide-top');
    } else {
      Navbar.$el.removeClass('-fixed uk-animation-slide-top');
    }
  } else {
    Navbar.$el.addClass('-fixed');
  }
};

$(window).on('load', Navbar.init);
$(window).on('scroll', Navbar.manage);

var Pagination = {
  
  conf: {
    prevButton: '.pagination__nav.-prev',
    nextButton: '.pagination__nav.-next',
    speed: 500,
    slidesPerView: 'auto',
    preventClicks: false,
    preventClicksPropagation: false,
    initialSlide: 0,
    freeMode: true,
    freeModeSticky: true
  },

  init: function($pagination_slider) {
    var conf = Object.create(Pagination.conf);
    conf.initialSlide = $pagination_slider.attr('data-active-page') - 1;
    var pagination = new Swiper($pagination_slider, conf);
  }
}

if ( $('.js-pagination-slider').length ) {
  Pagination.init($('.js-pagination-slider'));
}

$(window).on( 'load', function() {
  var percentage_bar = $('.js-percentage-bar');

  if( percentage_bar.length ) {
    var percentage = 0;
    var id = 0;
    percentage_bar.each( function(i) {
      percentage = $(this).attr('data-percentage') * 100 + '%';
      id = $(this).attr('id');
      var styleElem = document.head.appendChild(document.createElement("style"));
      styleElem.innerHTML = '#' + id + ':before {width:' + percentage + ';}';
    });
  }
});

;(function () {

  var PercentageCircle = {};
  PercentageCircle.$circle = $('.js-percentage-circle');

  PercentageCircle.paint = function ( iteration, value ) {
    
    // Exit on final iteration
    if ( iteration > value ) return;
    
    var distance_to_center, 
        bar_width;

    var radius = PercentageCircle.radius,
        extra_width = PercentageCircle.extra_width;

    var $circle = PercentageCircle.$circle,
        $bar = PercentageCircle.$bar,
        $filling = PercentageCircle.$filling,
        $value_display = PercentageCircle.$value_display;

    distance_to_center = radius * ( 1 - 2 * ( 1 - iteration/100 ) );
    bar_width = extra_width + radius + Math.sqrt( Math.pow(radius, 2) - Math.pow(distance_to_center, 2) );

    setTimeout(function() {
      
      // Apply Styles
      $bar.css({
        'width': bar_width,
        'top' : Math.round((1 - iteration/100) * 100) + '%',
        'transform': 'translateZ(0)'
      });
      $filling.css({
        'top' : Math.round((1 - iteration/100) * 100) + '%',
        'transform': 'translateZ(-1)'
      });
      $circle.css({
        'transform': 'translateZ(0)'
      });

      $value_display.html(iteration + '%');
      
      iteration++;
      PercentageCircle.paint(iteration, value);
    }, 0);
  };

  PercentageCircle.init = function () {

    var $percentage_circle = PercentageCircle.$circle;
    if ( !$percentage_circle.length ) return;
  
    // DOM Elements
    PercentageCircle.$bar            = $('#' + $percentage_circle.attr('data-bar'));
    PercentageCircle.$filling        = $('#' + $percentage_circle.attr('data-fill'));
    PercentageCircle.$value_display  = $('#' + $percentage_circle.attr('data-value-display'));
    
    // Values
    var value = parseInt($percentage_circle.attr('data-value'));
    if ( 100 < value ) {
      value = 100;
    } else if ( 0 > value ) {
      value = 0;
    }

    PercentageCircle.radius      = parseInt($percentage_circle.css('width')) / 2;
    PercentageCircle.extra_width = PercentageCircle.radius * 0.735;

    PercentageCircle.paint(0, value);

  };


  if ( PercentageCircle.$circle.length ) {
    PercentageCircle.init();

    $(window).on( 'mobile', function(e) {
      PercentageCircle.init();
    } );

  }

})();

$(document).ready(function() {
  $('.js-print-page').on('click', function(e){
    e.preventDefault();
    window.print();
  });
});

/**
 * Search Box Suggestions
 */

$(document).ready(function() {
  
  // No Web Storage support
  if ( typeof(Storage) === "undefined" ) {
    return;
  }

  // Save query in localstorage on submition
  $('.js-searchform').submit(function(e) {
    
    // Get previoues searches from localstorage
    var history = JSON.parse(localStorage.getItem('searchform_history'));
    history = history ? history : [];

    // Get Query from input field
    var query = $('.js-searchform [type="search"]').val();

    // Search history for same string
    var found_query = history.some(function(item, index, array){
      return query.toLowerCase() === item.value.toLowerCase()
    });
    
    // Push query to localstorage if it's not found
    if ( !found_query ) {
      history.push({
        value: query.toLowerCase(),
        data: new Date().getTime()
      });
      localStorage.setItem('searchform_history', JSON.stringify(history));
    }

    return;
  });
  
  // Get history from localstorage
  var suggestions = JSON.parse(localStorage.getItem('searchform_history'));
      
  // Start autocomplete
  var $searchform_input;
  var $searchform_inputs = $('.js-searchform-input');
  $searchform_inputs.each( function(i, el) {
    $searchform_input = $searchform_inputs.eq(i);
    $searchform_input.autocomplete({
      lookup: suggestions ? suggestions : [],
      appendTo: $searchform_input.attr('data-suggestions-container'),
      minChars: 2,
      maxHeight: 200
    })
  });

});
  
$(document).ready( function(e) {
  $('.js-searchform-submit').on('click', function(e) {
    e.preventDefault();

    var $search_form = $('#' + $(this).attr('data-form-id'));
    if ( $search_form.find('input').val() ) {
      $search_form.submit();
    }  
  });
});

$('.sitemap .menu-item.menu-item-has-children > a').on('click', function(e) {
  if ( breakpoint.mobile_max >= window.innerWidth ) { 
    $(this).parent().siblings().removeClass('-open');
    $(this).parent().toggleClass('-open'); 
  }
});
;(function () {
  'use strict';

  var Spinner = {};
  
  Spinner.dom = $('#spinner');

  Spinner.exists = function() {
    return !!Spinner.dom.length;
  };

  Spinner.hide = function() {
    Spinner.dom.addClass('hidden');
  };

  Spinner.show = function() {
    Spinner.dom.removeClass('hidden'); 
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = Spinner;
  } else {
    window.Spinner = Spinner;
  }
})();

$(document).ready(function(){
  if ( !('ontouchstart' in document.documentElement) ) {
    $('img.js-zoom-img')
      .wrap('<span style="display:inline-block; width:100%"></span>')
      .css('display', 'block')
      .parent()
      .zoom();
  }
});

var ArchiveAuction = {};

ArchiveAuction.$covers_slider = $('#auction-covers-slider');
ArchiveAuction.$info_slider = $('#auctions-info-slider');
ArchiveAuction.$timeline = $('#timeline-auctions');

ArchiveAuction.selectTimelineEvent = function( id ) {  
  ArchiveAuction.$timeline.find('.timeline__event').removeClass('-active');
  ArchiveAuction.$timeline.find('.timeline__event#' + id).addClass('-active');
  ArchiveAuction.$timeline[0].swiper.slideTo(id);
};

ArchiveAuction.setupSlider = function() {

  // Info Slider
  if ( ArchiveAuction.$info_slider.length ) {

    var info_slider_conf = {
      autoHeight : true,
      effect : 'fade',
      fade : {
        crossFade: false
      },
      onlyExternal : true,
      preventClicks : false,
      preventClicksPropagation : false,
      virtualTranslate: true
    };

    if ( breakpoint.mobile_max >= window.innerWidth ) {
      info_slider_conf.effect = 'slide';
      info_slider_conf.virtualTranslate = true;
    }

    new Swiper('#auctions-info-slider', info_slider_conf);
  }

  // Covers Slider
  if ( ArchiveAuction.$covers_slider.length ) {
    
    var covers_slider_conf = {};
    if ( breakpoint.mobile_max >= window.innerWidth ) {
      covers_slider_conf = SliderItunes.mobileConf;
      covers_slider_conf.scrollbar = '#auction-covers-scrollbar';
      covers_slider_conf.scrollbarHide = false;
    } else {
      covers_slider_conf = SliderItunes.conf;
    }
    covers_slider_conf.onInit = function(swiper) {
      ArchiveAuction.$covers_slider.removeClass('invisible');
      Spinner.hide();
    };

    if ( breakpoint.mobile_max >= window.innerWidth ) {
      covers_slider_conf.onTransitionEnd = function(swiper) {
        ArchiveAuction.$info_slider[0].swiper.slideTo(swiper.realIndex);
        ArchiveAuction.$covers_slider.find('.swiper-slide > a').hide();
        ArchiveAuction.$covers_slider.find('.swiper-slide-active > a').show();
      };
    } else {
      covers_slider_conf.onTransitionEnd = function(swiper) {  
        ArchiveAuction.selectTimelineEvent(swiper.realIndex);
      };
    }

    if ( breakpoint.mobile_max >= window.innerWidth ) {
      ArchiveAuction.$covers_slider.find('a').on('touchend click', function(e) {
        if ( !$(this).parent().hasClass('swiper-slide-active') ) {
          e.preventDefault();
        }
      });
    }

    new Swiper('#auction-covers-slider', covers_slider_conf);
    if ( breakpoint.mobile_max < window.innerWidth ) {
      ArchiveAuction.$covers_slider[0].swiper.params.control = ArchiveAuction.$info_slider[0].swiper;
    }
  }
};

ArchiveAuction.setupTimeline = function() {

  var timeline_slider_conf = {
    freeMode : true,
    freeModeSticky : true,
    grabCursor : true,
    mousewheelControl : true,
    mousewheelSensitivity : 0.75,
    preventClicks : false,
    preventClicksPropagation : false,
    scrollbar : '#timeline-scrollbar',
    setWrapperSize : true,
    slidesPerView : 'auto'
  };
  new Swiper('#timeline-auctions', timeline_slider_conf);

  /**
   * Injects class to target's adjancent elements
   * in order to apply styles.
   * 
   * Removes the class when mouse leaves the element.
   */
  ArchiveAuction.$timeline.find('.timeline__event').each(function (type) {
    $(this).hover(function() {
      $(this).prev('.timeline__event').addClass('-adjacent');
      $(this).next('.timeline__event').addClass('-adjacent');
    },
    function () {
      $(this).prev('.timeline__event').removeClass('-adjacent');
      $(this).next('.timeline__event').removeClass('-adjacent');
    });
  });

  /**
   * In case of auctions timeline, get ID from element
   * and execute slideToAuction() 
   */
  ArchiveAuction.$timeline.find('.timeline__event').each(function (type) {

    $(this).on('click', function(e) {
      ArchiveAuction.$timeline.find('.timeline__event').removeClass('-active');
      $(this).addClass('-active');
      ArchiveAuction.$covers_slider[0].swiper.slideTo($(this).attr('id'));
    });
  });
};

ArchiveAuction.resetSliders = function() {

  var activeIndex = ArchiveAuction.$covers_slider[0].swiper.activeIndex;
  
  ArchiveAuction.$covers_slider[0].swiper.destroy(false, true);
  ArchiveAuction.$info_slider[0].swiper.destroy(false, true);

  ArchiveAuction.setupSlider();
  ArchiveAuction.setupTimeline();

  ArchiveAuction.$covers_slider[0].swiper.slideTo(activeIndex);
};

ArchiveAuction.init = function() {
  ArchiveAuction.setupTimeline();
  ArchiveAuction.setupSlider();
  ArchiveAuction.$covers_slider.bind('mousewheel DOMMouseScroll', function (e) { return false; });


  $(window).on('mobile', function(e) {
    ArchiveAuction.resetSliders();
  });
};

var SingleAuction = {};

SingleAuction.$lots_list = $('#lots-list');

SingleAuction.LotsFilter = {

  default_params: {
    auction_number: 0,
    auction_session: 0,
    cat: 0,
    posts_per_page: 60,
    order_by: 'number',
    order: 'asc',
    view: 'list',
    page: 1
  },

  params: {},

  setup: function () {

    if ($('#no-lots-warning').length) return;

    wp.api.loadPromise.done(function () {
      SingleAuction.LotsFilter.params = Object.create(SingleAuction.LotsFilter.default_params);
      SingleAuction.LotsFilter.params.auction_number = SingleAuction.$lots_list.attr('data-auction-number');

      var session = queryString.get('session');
      var cat = queryString.get('cat');
      var order_by = queryString.get('order_by');
      var order = queryString.get('order');
      var page = queryString.get('current_page');
      var posts_per_page = queryString.get('posts_per_page');

      if (undefined !== session) {
        SingleAuction.LotsFilter.params.auction_session = session;
      } else {
        var current_session = $('#auction-lots-filters').data('current-session');
        if (current_session) {
          SingleAuction.LotsFilter.params.auction_session = current_session;
          queryString.push('session', current_session, true);
        }
      }
      if (undefined !== cat) {
        SingleAuction.LotsFilter.params.cat = cat;
      }
      if (undefined !== order_by) {
        SingleAuction.LotsFilter.params.order_by = order_by;
      }
      if (undefined !== order) {
        SingleAuction.LotsFilter.params.order = order;
      }
      if (undefined !== page) {
        SingleAuction.LotsFilter.params.page = page;
      }
      if (undefined !== posts_per_page) {
        SingleAuction.LotsFilter.params.posts_per_page = posts_per_page;
      }

    });

    $('.js-lots-filter').on('click', function (e) {
      e.preventDefault();

      // If filter is active
      // Do nothing
      if ($(this).hasClass('-active')) return;

      $('#no-lots-found').addClass('hidden');
      $('#navigation').addClass('hidden');

      var filter_type = $(this).attr('data-filter-type');
      var new_params = SingleAuction.LotsFilter.params;

      $(this).parent().siblings().children('.filter').removeClass('-active');
      SingleAuction.emptyLotsList();

      if ('session' === filter_type) {

        var session = $(this).attr('data-auction-session');
        new_params.auction_session = session;
        queryString.push('session', session, true);

        var $tab = $(this).parent();
        $tab.siblings().removeClass('-active');
        $tab.addClass('-active');

      } else if ('category' === filter_type) {

        var cat = $(this).attr('data-cat');
        new_params.cat = cat;
        queryString.push('cat', cat, true);

      } else if ('order' === filter_type) {

        var order_by = $(this).attr('data-order-by');

        switch (order_by) {
          case 'number':
            order_by = 'number';
            break;
          case 'author':
            order_by = 'author';
            break;
          case 'price':
            order_by = 'estimation_min';
            break;
          default:
            break;
        }
        new_params.order_by = order_by;
        queryString.push('order_by', order_by, true);

        var order = $(this).attr('data-order');
        if ('asc' === order || 'desc' === order) {
          new_params.order = order;
          queryString.push('order', order, true);
        }

      } else if ('posts-per-page' === filter_type) {
        var posts_per_page = $(this).attr('data-posts-per-page');
        new_params.posts_per_page = posts_per_page;
        queryString.push('posts_per_page', posts_per_page, true);
      }

      queryString.push('current_page', 1, true);
      new_params.page = 1;
      $(this).addClass('-active');

      if ($(document).scrollTop() > SingleAuction.$lots_list.offset().top) {
        SingleAuction.scrollToTop();
      }
      SingleAuction.LotsFilter.params = new_params;
      SingleAuction.loadLots(true);

    });

    var pagination = $('.js-pagination-slider')[0].swiper;
    pagination.on('tap', function (swiper) {
      var $page_link = $(swiper.clickedSlide).children('.lot-page');

      if ($page_link.hasClass('-active')) return;

      var page = $page_link.attr('data-page');
      queryString.push('current_page', page, true);
      $page_link.parent().siblings().children('.page-link').removeClass('-active');

      SingleAuction.scrollToTop();
      SingleAuction.emptyLotsList();
      SingleAuction.LotsFilter.params.page = $page_link.attr('data-page');

      $page_link.addClass('-active');
      SingleAuction.loadLots();
    });

    $('.js-lots-view').on('click', function (e) {
      e.preventDefault();
    });
  }
};

SingleAuction.appendLots = function (lots) {

  if (0 < lots.length && 4 > lots.length) {
    SingleAuction.$lots_list.addClass('-flex-start');
  }

  if (0 < lots.length) {

    var lotsArray = [];

    $.each(lots, function (index, value) {

      lotsArray.push({
        id: value.id,
        link: value.link,
        thumbnail: null != value.thumbnail ? value.thumbnail : wp_vars.images_folder + '/default_image.png',

        ref: value.fields.ref,
        name: value.fields.author_name ?
          (value.fields.name.length > 84 ? value.fields.name.substr(0, 84) + '...' : value.fields.name) :
          (value.fields.name.length > 43 ? value.fields.name.substr(0, 43) + '...' : value.fields.name),
        author: value.fields.author_name.length > 43 ?
          value.fields.author_name.substr(0, 43) + '...' :
          value.fields.author_name,

        estimation_min: parseFloat(value.fields.estimation_min).toLocaleString('de-DE'),
        estimation_max: parseFloat(value.fields.estimation_max).toLocaleString('de-DE'),
        price_on_request: value.fields.price_on_request,

        is_favorite: value.is_favorite,
        is_in_order: value.is_in_order,
      });

    });

    var template = _.template($('#lot-card-template').html());
    var htmlCompiled = template({
      lots: lotsArray,
      isLoggedin: $('body').attr('data-client-loggedin'),
      isEmailConfirmed: $('body').attr('data-client-confirmed')
    });
    SingleAuction.$lots_list.html(htmlCompiled);

    $('#navigation').removeClass('hidden');
    $('#no-lots-found').addClass('hidden');
  } else {
    $('#no-lots-found').removeClass('hidden');
    $('#navigation').addClass('hidden');
  }

};

SingleAuction.buildPagination = function (total, totalpages, page = 1) {

  if (1 < totalpages) {

    $('#pagination').removeClass('hidden');
    var pagination = $('.swiper-container.js-pagination-slider')[0].swiper;
    pagination.removeAllSlides();
    pagination.appendSlide(`<li class="swiper-slide pagination__page"><a href="#" class="pagination__page-link page-link lot-page js-disable-link ${page == 1 ? '-active' : ''}" data-page="1">1</a></li>`);
    for (var i = 2; i <= totalpages; i++) {
      pagination.appendSlide(`<li class="swiper-slide pagination__page"><a href="#" class="pagination__page-link page-link lot-page js-disable-link ${page == i ? '-active' : ''}" data-page="${i}">${i}</a></li>`);
    }
  } else {
    $('#pagination').addClass('hidden');
  }
};

/**
 * Get Lots from WP REST API and injects content into lot list
 * @param {Object} params Query for WP REST API. Must obey the following structure:
 * {
 *   auction_number: 0,
 *   auction_session: 0,
 *   cat: 0,
 *   posts_per_page: 50,
 *   order_by: 'number',
 *   order: 'asc',
 *   view: 'list',
 *   page: 1
 * }
 *
 */
SingleAuction.loadLots = function (resetPagination, init = false) {

  var _params = SingleAuction.LotsFilter.params;
  var _url = wp_vars.ajax_routes.lot_list;

  setTimeout(function () {
    $.ajax({
      url: _url,
      dataType: 'json',
      type: 'get',
      data: SingleAuction.LotsFilter.params,
      success: function (data, textStatus, httpRequest) {
        setTimeout(() => {
          Spinner.hide();
          if (init) {
            SingleAuction.buildPagination(data.total_posts, data.total_pages, _params.page)
          }
          if (resetPagination) {
            SingleAuction.buildPagination(data.total_posts, data.total_pages)
          }
          SingleAuction.appendLots(data.posts);

        }, 200);
      }
    });
  }, 1000);
};

SingleAuction.scrollToTop = function () {
  $('html, body').animate({
    scrollTop: SingleAuction.$lots_list.offset().top - 200,
  }, 100);
};

SingleAuction.emptyLotsList = function () {
  SingleAuction.$lots_list.fadeOut(150, function () {
    $(this).empty().show();
    Spinner.show();
  });
};

SingleAuction.setupSlider = function () {

  if (!$('#featured-lots-slider').length) {
    return;
  }

  var featured_lots_slider_conf = {
    slidesPerView: 1,
    spaceBetween: 0,

    autoHeight: true,
    centeredSlides: true,
    grabCursor: true,

    speed: 400,
    effect: 'coverflow',
    coverflow: {
      rotate: 50,
      stretch: 0,
      depth: 100,
      modifier: 1,
      slideShadows: false
    },

    freeMode: false,
    freeModeSticky: false,

    slideToClickedSlide: true,
    keyboardControl: true,
    mousewheelControl: false,
    paginationClickable: true,
    prevButton: '#featured-lots-slider-button-prev',
    nextButton: '#featured-lots-slider-button-next',
  };

  new Swiper('#featured-lots-slider', featured_lots_slider_conf);
}

function veritasOpenAuctionModalbyHash() {
  if (window.location.hash === '#issuu') {
    var catalogModal = UIkit.modal("#catalog-browser");
    catalogModal.show();

    // Tag Manager Data object
    trackHashDataLayer('catalog-browser');
  }
  if (window.location.hash === '#virtualviewing' || window.location.hash === '#virtual-viewing' || window.location.hash === '#visitavirtual' || window.location.hash === '#visita-virtual') {
    var virtualModal = UIkit.modal("#virtual-viewing");
    virtualModal.show();

    // Tag Manager Data object
    trackHashDataLayer('virtual-viewing');
  }
}

function trackHashDataLayer(hashName) {
  var auctionNumber = $('#auction__number__getter').data('auction-number');
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({
    'event': 'auction_action',
    'auction_action': hashName,
    'auction_action_ID': auctionNumber
  });
}

SingleAuction.init = function () {

  if ($('body').hasClass('verbetes')) return;

  SingleAuction.setupSlider();

  $('#filters-toggle-button-open, #filters-toggle-button-filter, #filters-toggle-button-close').on('click', function (e) {
    e.preventDefault();
    $('#auction-lots-filters').toggleClass('-open');
  });

  SingleAuction.LotsFilter.setup();

  var browse_catalog = queryString.get('browse_catalog');
  if (undefined !== browse_catalog && 'undefined' !== browse_catalog) {
    UIkit.modal('#catalog-browser').show();
  }

  SingleAuction.loadLots(false, true);

  window.onload = veritasOpenAuctionModalbyHash;
  window.addEventListener('hashchange', veritasOpenAuctionModalbyHash);
};

var SingleLot = {};

SingleLot.$thumbs = $('#lot-thumbs');
SingleLot.$gallery = $('#lot-gallery');

SingleLot.gallery_slider = null;
SingleLot.thumbs_slider = null;

SingleLot.setupGallery = function () {

  // Setup lot gallery
  var lot_gallery_conf = {
    autoHeight: true,
    effect: 'fade',
    fade: {
      crossFade: true
    },
    speed: 400,
    onTransitionEnd: function (swiper) {

      SingleLot.thumbs_slider.slideTo(swiper.activeIndex);
      SingleLot.$thumbs.find('.swiper-slide').removeClass('-active');
      SingleLot.$thumbs.find('.swiper-slide#' + swiper.activeIndex).addClass('-active');

      // Scroll up the page on click in thumbnails if necessary
      var lot_gallery_offset = SingleLot.$gallery.offset().top;
      if ($(document).scrollTop() > lot_gallery_offset) {
        $('html, body').animate({
          scrollTop: lot_gallery_offset - (Navbar.$el.height() + 20),
        }, 500);
      }
    },
    onClick: function (swiper) {
      var lightbox_img_url = $(swiper.clickedSlide).find('img[data-lity-target]').attr('data-lity-target');
      lity(lightbox_img_url);
    },
  };
  SingleLot.gallery_slider = new Swiper('#lot-gallery', lot_gallery_conf);

  // Setup gallery thumbnails
  var lot_thumbs_conf = {
    scrollbar: '#lot-thumbs-scrollbar',
    scrollbarHide: false,
    scrollbarDraggable: false,
    scrollbarSnapOnRelease: false,
    spaceBetween: 10,
    slidesPerView: 'auto',
    slideToClickedSlide: true,
    grabCursor: true,
    onClick: function (swiper, event) {
      if (swiper.clickedIndex >= 0) {
        SingleLot.gallery_slider.slideTo(swiper.clickedIndex);
      }
    },
    onInit: function (swiper) {
      SingleLot.$thumbs.find('.swiper-slide#' + swiper.realIndex).addClass('-active');
    }
  };

  SingleLot.thumbs_slider = new Swiper('#lot-thumbs', lot_thumbs_conf);

  // Setup zoom on full-screen
  $(document).on('click', '.lity-opened.lity-image .lity-container', function (e) {

    var $lity_container = $(this);
    var $img = $lity_container.children('.lity-content').children('img');

    var cursor = {
      x: e.pageX - $img.offset().left,
      y: e.pageY - $img.offset().top
    };

    var imgPosition = {
      x: cursor.x / $img.width(),
      y: cursor.y / $img.height(),
    };

    var toggled = $lity_container.toggleClass('-expand').hasClass('-expand');
    if (toggled) {
      $('html').addClass('uk-overflow-hidden');

      var scrollX = imgPosition.x * ($img.width() - window.innerWidth);
      var scrollY = imgPosition.y * ($img.height() - window.innerHeight);

      if (0 < scrollX) $lity_container.scrollLeft(scrollX);
      if (0 < scrollY) $lity_container.scrollTop(scrollY);

    } else {
      $('html').removeClass('uk-overflow-hidden');
    }
  });
  // Prevent hidden overflow on body after full-screen zoom
  $(document).on('click', '.lity-close', function (e) {
    $('html').removeClass('uk-overflow-hidden');
  });
};

SingleLot.setupAddLot = function () {

  var $form_container = $('#order-placement-form-container');
  var $form = $('#order-placement-form');

  $form.submit(function (e) {
    e.preventDefault();
    $('.form__error').removeClass('-shown');
    if (SingleLot.validateValue()) {

      var order_value_clean = $('#client-lot-value').cleanVal();
      $('#client-lot-value').val(order_value_clean);

      var _data = {
        'nonce': wp_vars.ajax_nonce,
        'lot-id': $form.attr('data-lot-id'),
        'auction-id': $form.attr('data-auction-id')
      }
      var _url = wp_vars.ajax_routes.order_addlot;

      $(this).ajaxSubmit({
        url: _url,
        data: _data,
        type: 'post',
        dataType: 'json',
        beforeSubmit: function (arr, $form, options) {
          Spinner.show();
          $form_container.hide();
        },
        success: function (response, statusText) {
          Spinner.hide();
          if ('success' === response.result) {

            LotsCounter.addLot();
            $form_container.fadeOut(200, function () {
              $form_container.remove();
              $('#order-placement-success').removeClass('hidden');
              location.reload();
            });

          } else if ('error' === response.result) {
            if ('not_logged_in' === response.message) {
              $form_container.remove();
              $('#order-placement-error-nologgin').removeClass('hidden');
            } else if ('not_confirmed' === response.message) {
              $form_container.remove();
              $('#order-placement-error-notconfirmed').removeClass('hidden');
            } else {
              $form_container.show();
            }
          } else {
            $form_container.show();
          }
        }
      });
    }
    return false;

  });
};

SingleLot.validateValue = function () {
  if ($('#order-type-value')[0].checked) {
    var $client_lot_value = $('#client-lot-value');

    if ($client_lot_value[0].checkValidity() && parseInt($client_lot_value.cleanVal()) < parseInt($client_lot_value.attr('data-min')) ||
      !$client_lot_value.val()) {
      $client_lot_value.trigger('invalid');
      return false;
    }

  } else if ($('#order-type-phone')[0].checked) {
    var has_number = 0;
    $('.js-client-contact').each(function (i, el) {
      if (el.value) {
        has_number++;
      }
    });

    if (!has_number) {
      $('.js-client-contact').trigger('invalid');
    }

    return !!has_number;
  }
  return true;
};

SingleLot.init = function () {
  SingleLot.setupGallery();
  SingleLot.setupAddLot();
};

var DeleteAccountForm = {};
  
DeleteAccountForm.setup = function() {

  $('#deleteaccount-form').submit( function(e) {
    e.preventDefault();

    // Submit form
    var _data = { 
      'action'  : 'deleteAccount',
      'nonce'   : wp_vars.ajax_nonce
    };

    var $deleteaccount_form = $('#deleteaccount-form-container');
    var $deleteaccount_success_message = $('#deleteaccount-success-message');

    $deleteaccount_form.fadeOut(100, function() {
      Spinner.show();
    });

    $(this).ajaxSubmit( {
      data: _data,
      url: wp_vars.ajax_url,
      type: 'post', 
      dataType: 'json',
      success: function(response, status) {
        Spinner.hide();
        if ( 'success' === response.result ) {
          $deleteaccount_success_message.removeClass('hidden');
        } else {
          if ( 'wrong_password' === response.error_type ) {
            $('#deleteaccount-password').trigger('invalid');
          }
          $deleteaccount_form.show();
          var error_message = response.error_message ? response.error_message : 'Error';
          document.getElementById('deleteaccount-form-error').innerHTML = error_message;
          $('#deleteaccount-form-error').addClass('-shown');
        }
      }
    } );
    
    // return false to prevent normal browser submit and page navigation 
    return false; 
  });
};

DeleteAccountForm.init = function() {
  DeleteAccountForm.setup();
};

var MyVeritas = {};

MyVeritas.setupRegistrationMessageForm = function() {

  if ( !$('#registration-message-form').length ) return;

  $('#registration-message-form').submit( function(e) {
    var _data = { 
      'action' : 'sendConfirmationEmail',
      'nonce' : wp_vars.ajax_nonce
    };
    Spinner.show();
    $('#registration-message').addClass('uk-hidden');
    $(this).ajaxSubmit( {
      data: _data,
      url: wp_vars.ajax_url,
      type: 'post', 
      dataType: 'json',
      success: function(responseText, statusText) {
        $('#registration-message-emailsent').removeClass('uk-hidden');
        Spinner.hide();
      }
    });

    // return false to prevent normal browser submit and page navigation 
    return false; 
  });
};

MyVeritas.setupNavigation = function () {

  if ( !$('#myveritas-page-navigation').length ) return;

  var navigation_scroll = new IScroll('#myveritas-page-navigation', { 
    scrollX: true, 
    scrollY: false, 
    mouseWheel: true 
  });
  navigation_scroll.scrollToElement('#myveritas-page-navigation .sub.sub-0 > .menu-item.-active', 500, -20);
};

MyVeritas.init = function() {
  MyVeritas.setupNavigation();
  MyVeritas.setupRegistrationMessageForm();
};

var LoginPage = {};

LoginPage.setupLoginForm = function() {

  var $login_form = $('#login-form');
  $login_form.on('submit', function(e) {
    e.preventDefault();
    
    var _data = { 
      'action' : 'loginUser',
      'nonce' : wp_vars.ajax_nonce
    };
    Cursor.load();
    $(this).ajaxSubmit( {
      data: _data,
      url: wp_vars.ajax_url,
      type: 'post', 
      dataType: 'json',
      success: function(response, status) {
        Cursor.default();
        if ( 'success' === response.result ) {
          window.location.href = wp_vars.myveritas_base_url + '/dashboard';
        } else {
          var error_message = response.error_message ? response.error_message : 'Error';
          document.getElementById('login-form-error').innerHTML = error_message;
          $('#login-form-error').addClass('-shown');
        }
      }
    } );
    
    // return false to prevent normal browser submit and page navigation
    return false; 
  });
};

LoginPage.setupForgotPasswordForm = function() {
    
  var $reset_form = $('#forgotpassword-form');
  var $submitted_email = $('#submitted_email');
  var $sentconfirmation = $('#forgotpassword-sentconfirmation');

  var $spinner = $('#spinner');

  $('#forgotpassword-link-desktop, #forgotpassword-link-mobile').on('click', function(e) {
    e.preventDefault();
    
    $('#login-form').fadeOut(200, function() {
      $reset_form.removeClass('hidden');
    });
  });

  $('#rewrite-email-link').on('click', function(e) {
    e.preventDefault();
    
    $sentconfirmation.fadeOut(200, function() {
      $reset_form.show();
    });
  });
  
  $reset_form.on('submit', function(e){
    e.preventDefault();
    
    var _data = { 
      'action'  : 'forgotPassword',
      'nonce'   : wp_vars.ajax_nonce
    };

    $reset_form.fadeOut(100, function() {
      Spinner.show();
      Spinner.dom.show();
    });
    $reset_form.ajaxSubmit( {
      data: _data,
      url: wp_vars.ajax_url,
      type: 'post', 
      dataType: 'json',
      success: function(response, status) {
        if ( 'success' === response.result ) {
          $spinner.fadeOut(100, function(){
            
            $submitted_email.empty();
            $submitted_email.append(response.submitted_email);
            
            $sentconfirmation.removeClass('uk-hidden');
            $sentconfirmation.show();
          });
        } else {
          $spinner.hide();
          $reset_form.show();
          $('.form__error').removeClass('-shown');
          $('#forgotpassword-wrong-email-error').addClass('-shown');
        }
      }
    });
    
    // Prevent default behaviour
    return false;
  });

};

LoginPage.init = function() {

  LoginPage.setupLoginForm();
  LoginPage.setupForgotPasswordForm();

  var reset_password = queryString.get('reset_password');
  if ( undefined !== reset_password && 'undefined' !== reset_password ) {
    $('#login-form').fadeOut(200, function() {
      $('#forgotpassword-form').removeClass('hidden');
    });
  } 

};

/**
 * Page: Order - Edit
 */
var OrderEdit = {};

OrderEdit.$form = $('#order-edit-form');

OrderEdit.setupUpdate = function () {

  OrderEdit.$form.submit(function (e) {
    e.preventDefault();

    $('.form__error').removeClass('-shown');

    if (OrderEdit.checkFieldsValidity()) {

      var _data = {
        'nonce': wp_vars.ajax_nonce,
        'order-id': $(this).attr('data-order-id')
      };

      var _url = wp_vars.ajax_routes.order_update;

      $(this).ajaxSubmit({
        url: _url,
        data: _data,
        type: 'post',
        dataType: 'json',
        beforeSubmit: function (arr, $form, options) {
          Spinner.show();
          OrderEdit.$form.hide();
          $('html, body').animate({
            scrollTop: 0,
          }, 500);
        },
        success: function (response, statusText) {

          if (response.order_canceled) {
            window.location = wp_vars.pages.myveritas.orders_unsubmitted;
          } else {
            location.reload();
          }
        }
      });
    }
    return false;
  });
};

OrderEdit.setupAreYouSure = function () {
  OrderEdit.$form.areYouSure({ message: wp_vars.strings.ays_warning });
};

OrderEdit.setupSubmitButton = function () {

  $('#order-submit-button').on('click', function (e) {
    e.preventDefault();

    $('.form__error').removeClass('-shown');

    if (OrderEdit.checkFieldsValidity()) {
      OrderEdit.saveOrder(function (response, statusText) {
        OrderEdit.$form.removeClass('dirty');
        window.location = $('#order-submit-button').attr('href');
      });
    }
  });
};

OrderEdit.checkFieldsValidity = function () {

  var inputs_valid = true;

  var $order_type_switchers = $('.js-order-type');
  var $order_type_switcher, targets, $target;

  $order_type_switchers.each(function (i, el) {

    if (el.checked) {

      $order_type_switcher = $order_type_switchers.eq(i);
      targets = $order_type_switcher.attr('data-target');

      var $input_fields = $(targets).find('.js-order-lot-value, .js-order-lot-phone');
      $input_fields.each(function (i, el) {
        $target = $input_fields.eq(i);
        var has_number = 0;
        if ($target.hasClass('js-order-lot-value')) {

          if (parseInt($target.cleanVal()) < parseInt($target.attr('data-min'))) {
            $target.trigger('invalid');
            inputs_valid = false;
          }
        } else if ($target.hasClass('js-order-lot-phone')) {

          var cross_input = $target.attr('data-cross-input');
          if (!$target.val() && !cross_input ||
            !$target.val() && cross_input && !$('#' + cross_input).val()) {
            $target.trigger('invalid');
            inputs_valid = false;
          }
        }
      });
    }
  });

  return inputs_valid;
};

OrderEdit.saveOrder = function (successFunction) {

  UIkit.modal('#remove-all-lots-modal').hide();

  var _url = wp_vars.ajax_routes.order_update;

  var _data = {
    'nonce': wp_vars.ajax_nonce,
    'order-id': OrderEdit.$form.attr('data-order-id')
  };

  OrderEdit.$form.ajaxSubmit({
    url: _url,
    data: _data,
    type: 'post',
    dataType: 'json',
    beforeSubmit: function (arr, $form, options) {
      Spinner.show();
      OrderEdit.$form.hide();
      $('html, body').animate({
        scrollTop: 0,
      }, 500);
    },
    success: successFunction ? successFunction : function (response, statusText) {
      OrderEdit.$form.removeClass('dirty');
      location.reload();
    }
  });
};

OrderEdit.setupOrderSave = function () {
  $('.js-save-order').on('click', function (e) {
    OrderEdit.saveOrder();
  });
};

OrderEdit.init = function () {
  OrderEdit.setupUpdate();
  OrderEdit.setupOrderSave();
  OrderEdit.setupAreYouSure();
  OrderEdit.setupSubmitButton();
};

var OrderSubmit = {};

OrderSubmit.$form = $('#order-submit-form');

OrderSubmit.setupSubmit = function() {
  
  $('#modal-order-submit-button').on( 'click', function(e) {
    $('.js-modal-close').click();
    var invalid_field = 0;
    OrderSubmit.$form.find('input').each( function(i, el) {

      if ( !el.checkValidity() ) {
        invalid_field++;
      }
    } );
    if ( !invalid_field ) {
      OrderSubmit.$form.trigger('submit');
    }
  } );

  $('#mobile-order-submit-button').on( 'click', function(e) {
    e.preventDefault();

    if ( $(this).hasClass('js-mobile-order-submit-open-modal') ) {
      UIkit.modal('#order-submit-modal').show();
    } else {
      $('#order-submit-button').click();
    }
  } );
  
  OrderSubmit.$form.submit( function(e) {
    e.preventDefault();

    var order_id = $(this).attr('data-order-id');
    
    var _data = {
      'nonce'     : wp_vars.ajax_nonce,
      'order-id'  : order_id
    };
    
    var _url = wp_vars.ajax_routes.order_submit;

    $(this).ajaxSubmit( {
      url: _url,
      data: _data,
      type: 'POST', 
      dataType: 'json',
      beforeSubmit: function(arr, $form, options) {
        Spinner.show();
        $('#order-submit-form-area').hide();
        $('html, body').animate({
          scrollTop: 0,
        }, 500);
      },
      success: function(response, statusText) {
        if ( 'success' === response.result ) {
          if ( response.hasOwnProperty('redirect_url') ) {
            window.location = response.redirect_url;
          } else {
            window.location = wp_vars.pages.myveritas.orders_unsubmitted;
          }
        } else {
          $('#order-submit-form-area').show();
        }
      }
    } );
    return false;
  } );
};

OrderSubmit.init = function() {
  OrderSubmit.setupSubmit();

  // Accordion JS logic
  $('.js-card-order-lot').on( 'click', function(e) {

    if ( window.innerWidth <= breakpoint.mobile_max && $(e.target).hasClass('card-order-lot__details') ) {
      $(this).toggleClass('-open');
    }
  } );
};

var Order = {};

Order.setupCancelOrder = function() {
  $('.js-cancel-order').on('click', function(e){
    e.preventDefault();

    var _url = wp_vars.ajax_routes.order_cancel;

    var _data = {
      'nonce'     : wp_vars.ajax_nonce,
      'order-id'  : $(this).attr('data-order-id')
    };

    $.ajax({
      url: _url,
      dataType: 'json',
      type: 'POST',
      data: _data,
      success: function (data, textStatus, httpRequest) {
        if ( 'success' === data.result ) {
          window.location = wp_vars.pages.myveritas.orders_submitted;
        } else {
          $('.js-modal-close').click();
        }
      }
    });
  });
};

Order.init = function() {
  Order.setupCancelOrder();
};

/**
 * Page - MyVeritas profile
 */
var ProfilePage = {};

ProfilePage.setupProfile = function() {

  $('#profile-form').submit(function(e) {
    e.preventDefault();

    // Check passwords reset validity 
    var $current_password = $('#profile-current-password');
    var $password_new = $('#profile-new-password');
    var $password_confirmation = $('#profile-new-password-confirmation');

    if ( $password_new.val() || $password_confirmation.val() ) {
      
      if ( $current_password.val() && $password_new.val() != $password_confirmation.val() ) {

        $password_confirmation.trigger('invalid');
        return;
        
      } else if ( !$current_password.val() ) {

        if ( $password_new.val() && $password_confirmation.val() ) {
          $current_password.trigger('invalid');
          return;
        } else if ( $password_new.val() && !$password_confirmation.val() ) {
          $password_confirmation.trigger('invalid');
          return;
        } else if ( !$password_new.val() && $password_confirmation.val() ) {
          $password_new.trigger('invalid');
          return;
        }
      }
    }

    if ( !ProfilePage.verifyCreditCard() ) {
      return;
    }

    var _data = { 
      'action' : 'updateUser',
      'nonce' : wp_vars.ajax_nonce
    };

    $('#profile-form').fadeOut(200, function(){
      Spinner.show();
      $('html, body').animate({
        scrollTop: 0,
      }, 500);
    });
    $(this).ajaxSubmit( {
      data: _data,
      url: wp_vars.ajax_url,
      type: 'post', 
      dataType: 'json',
      cache : false,
      clearForm: true,
      success: function(response, status) {
        if ( 'success' === response.result ) {
          window.location.search = '&saved=true&tab=' + $('.js-wizard-tab.uk-active').attr('data-tab');
        } else {
          var error_message = response.error_message ? response.error_message : 'Error';
          document.getElementById('profile-form-error').innerHTML = error_message;
          $('#profile-form-error').addClass('-shown');
        }
      }
    });
    
    
    // return false to prevent normal browser submit and page navigation 
    return false; 
  });
};


ProfilePage.verifyCreditCard = function () {

  var credit_card_number = $('#profile-card-number')[0].value;
  var credit_card_security_code = $('#profile-card-security-code')[0].value;
  var credit_card_validity = $('#profile-card-validity')[0].value;
  
  if ( credit_card_number || credit_card_security_code || credit_card_validity ) {
    
    // Verifica tipo de cartão de crédito
    if ( !card(credit_card_number).getType() ) {
      $('#profile-card-number').trigger('invalid');
      $('#credit-card-field-error').addClass('-shown');
      return false;
    }
    // Verifica código de segurança
    if ( credit_card_security_code.length != 0 && !(/(^\d{3}$)|(^\d{4}$)/.test(credit_card_security_code)) ) {
      $('#profile-card-security-code').trigger('invalid');
      $('#credit-card-field-error').addClass('-shown');
      return false;
    }
    
    // Verifica data válida
    if (  ( credit_card_validity.length != 0 && !(/(0?[1-9]|1[0-2])\/(\d{2})/.test(credit_card_validity)) ) ||
          ( credit_card_validity.length == 0 && credit_card_number.length != 0 ) 
        ) {
      $('#profile-card-validity').trigger('invalid');
      $('#credit-card-field-error').addClass('-shown');
      $('#credit-card-validity-error').addClass('-shown');
      return false;
    }
  }
  return true;
    
};

ProfilePage.init = function() {

  $('li a[href="/myveritas/profile"]').parent().addClass('-active');

  // Clean Credit Card values if incomplete
  var $credit_card_number = $('#profile-card-number');
  var $credit_card_security_code = $('#profile-card-security-code');
  var $credit_card_validity = $('#profile-card-validity');

  if ( ! ($credit_card_number[0].value && $credit_card_security_code[0].value && $credit_card_validity[0].value) ) {
    $credit_card_number.val('');
    $credit_card_security_code.val('');
    $credit_card_validity.val('');

    $('.input__placeholder[for=' + $credit_card_number.attr('id') + ']').removeClass('-focus -focused');
    $('.input__placeholder[for=' + $credit_card_security_code.attr('id') + ']').removeClass('-focus -focused');
    $('.input__placeholder[for=' + $credit_card_validity.attr('id') + ']').removeClass('-focus -focused');
  }

  ProfilePage.setupProfile();
  
  var update_successful = $('#profile-update-successful');
  if( getUrlVar('saved') ) {
    update_successful.removeClass('hidden');
    
    setTimeout(function() {
      update_successful.fadeOut(1500, function() {
        $(this).addClass('hidden');
      });
    }, 4000);
    
    var targetTab = getUrlVar('tab');
    if ( targetTab ) {
      $('.js-wizard-tab[data-tab="'+ targetTab +'"]').click();
    }

    history.replaceState({}, null, window.location.href.split('?')[0]);
    
  }


  // Hide file display on 'remove'
  $('#profile-remove-document').change(function(){
    if ( this.checked ) {
      var file_label = $('[for=' + this.id + ']');
      file_label.parent().hide();
    }
  });

  $('#bank-fields-switcher').on('click', function( e ) {
    if ( !ProfilePage.verifyCreditCard() ) {
      e.preventDefault();
    } else {
      $('.form__error[for="profile-card-number"]').removeClass('-shown');
      $('#card-fields input').removeClass('invalid');
    }
  });
  
};
/**
 * Page - Myveritas Registration
 */
var RegistrationPage = {};

RegistrationPage.setupForm = function() {

  var $registration_form = $('#registration-form');
  $registration_form.submit( function(e) {
    e.preventDefault();

    // Check Password
    var $password = $('#registration-password');
    var $password_confirmation = $('#registration-password-confirmation');
    if ( $password[0].value !== $password_confirmation[0].value ) {
      $password_confirmation.trigger('invalid');
      $('#password-confirmation-error').addClass('-shown');
      return;
    }

    var $registration_error = $('#registration-form-error');

    // Check privacy policy compliance
    var $privacy_policy_compliance = $('#registration-privacy-policy-compliance');
    if ( !$privacy_policy_compliance[0].checked ) {
      $registration_error.addClass('-shown');
      $registration_error.show();
      $privacy_policy_compliance.addClass('invalid')
      return;
    }

    
    // Fade out registration form
    var $registration_area = $('#registration-area');
    $registration_area.fadeOut(200, function() {
      Spinner.show();
      $('html, body').animate({
        scrollTop: 0,
      }, 500);
    });

    // Submit
    var _url = wp_vars.ajax_url;
    var _data = { 
      'action' : 'createUser',
      'nonce' : wp_vars.ajax_nonce
    }; 
    $(this).ajaxSubmit( {
      data: _data,
      url: _url,
      type: 'post', 
      dataType: 'json',
      success: function( response, status ) {
        
        if ( 'success' === response.result ) {
          $('#registration-message').removeClass('uk-hidden');
          Spinner.hide();
        } else {
          var error_message = response.error_message ? response.error_message : 'Error';
          document.getElementById('registration-form-error').innerHTML = error_message;
          $('#registration-form-error').addClass('-shown');
          $('#registration-form-error').show();
          Spinner.hide();
          $registration_area.show();

          if ( 'existing_user_login' === response.error || 'existing_user_email' === response.error ) {  
            $('#registration-email').trigger('invalid');
          }

          $('html, body').animate({
            scrollTop: $registration_error.offset().top - Navbar.$el.height()
          }, 250);
          $('#identification-tab').click();
        }
      }
    });
  });
};

RegistrationPage.setupWizard = function() {
  
  var $next_step_button = $('#registration-next-step');
  var $submit_button = $('#registration-submit');

  $next_step_button.on('click', function(e) {
    e.preventDefault();
  
    var next_step = $(this).attr('data-next-step');
    var $next_step_tab = $('#' + next_step + '-tab');
    var next_step_container = $('#' + next_step);
    
    // Check if passwords match
    var $password = $('#registration-password');
    var $password_confirmation = $('#registration-password-confirmation');
    if ( $password.val() != $password_confirmation.val() ) {
      $password_confirmation.trigger('invalid');
      $('#password-confirmation-error').addClass('-shown');
      return;
    }

    // Check if inputs are valid
    var invalid_inputs = 0;
    var $step_inputs = $('#' + $next_step_tab.siblings('.uk-active').attr('id').replace(/-tab$/, "") + ' ' + 'input');
    $step_inputs.each( function(index){
      var $step_input = $step_inputs.eq(index);
      if ( !$step_input[0].checkValidity() ) {
        invalid_inputs++;
      }
    } );

    // Go to next step if there's no errors
    if ( 0 === invalid_inputs ) {
      $next_step_tab.removeClass('no_link');
      $next_step_tab.click();
      $('.js-form-error').hide();

      // Scroll up the page on click in thumbnails if necessary
      var registration_form_offset = $('#registration-form').offset().top;
      if ( $(document).scrollTop() > registration_form_offset ) {
        $('html, body').animate({
          scrollTop: registration_form_offset - (Navbar.$el.height() + 10),
        }, 500);
      }
    }
  });

  // Show Submit button only when user is on last tab
  $('#registration-fields > *').on('show', function () {
    var $step_tab = $('#' + $(this).attr('id') + '-tab');

    if ( $step_tab[0].hasAttribute('data-final-tab') ) {
      $next_step_button.hide();
      $submit_button.removeClass('hidden');
      $submit_button.removeClass('-disabled');
      $('#registration-submit input[type="submit"]').prop('disabled', false);
      $next_step_button.attr('data-final-tab', true);
    } else {
      $next_step_button.show();
      $submit_button.addClass('hidden');
      $submit_button.addClass('-disabled');
      $('#registration-submit input[type="submit"]').prop('disabled', true);
      $next_step_button.attr('data-final-tab', false);
    }

    var $next_step_tab = $step_tab.next();
    if ( $next_step_tab.length ) {
      var next_step = $next_step_tab.attr('id').replace(/-tab$/, "");
      $next_step_button.attr('data-next-step', next_step);
    }
  });

  // Go to next step when ENTER is pressed
  $(document).keypress(function (e) {
    var key = e.which || e.keyCode;
    if ( 13 === key ) { // 13 - ENTER key
      e.preventDefault();
      if ( 'false' == $next_step_button.attr('data-final-tab') ) {
        $next_step_button.click();
      } else {
        $('#registration-form').submit();
      }
    }
  });
};

RegistrationPage.init = function() {
  RegistrationPage.setupForm();
  RegistrationPage.setupWizard();
};

var ResetPasswordForm = {};

ResetPasswordForm.setup = function (form_options) {

  $('#resetpassword-form').submit(function (e) {
    // Check if password and confirmation values match
    var password = $('#resetpassword-password');
    var password_confirmation = $('#resetpassword-confirmation');
    if (password[0].value !== password_confirmation[0].value) {
      password_confirmation.trigger('invalid');
      return;
    }

    // Submit form
    var _data = {
      'action': 'resetPassword',
      'nonce': wp_vars.ajax_nonce,
      'reset': getUrlVar('reset')
    };
    $(this).ajaxSubmit({
      data: _data,
      url: wp_vars.ajax_url,
      type: 'post',
      dataType: 'json',
      success: function (response, status) {
        if ('success' === response.result) {
          window.location.href = wp_vars.myveritas_base_url + '/login';
        } else {
          var error_message = response.error_message ? response.error_message : 'Error';
          document.getElementById('resetpassword-form-error').innerHTML = error_message;
          $('#resetpassword-form-error').addClass('-shown');
        }
      }
    });

    // return false to prevent normal browser submit and page navigation 
    e.preventDefault();
    return false;
  });
};

ResetPasswordForm.init = function () {
  ResetPasswordForm.setup();
};

/* ========================================================================
 * DOM-based Routing
 * Based on http://goo.gl/EUTi53 by Paul Irish
 *
 * Only fires on body classes that match. If a body class contains a dash,
 * replace the dash with an underscore when adding it to the object below.
 *
 * .noConflict()
 * The routing is enclosed within an anonymous function so that you can
 * always reference jQuery with $, even when in .noConflict() mode.
 * ======================================================================== */

(function ($) {

  // Use this variable to set up the common and page specific functions. If you
  // rename this variable, you will also need to rename the namespace below.
  var Sage = {
    // All pages
    'common': {
      init: function () {
        // Lots Counter
        LotsCounter.init();

        // Privacy Policy Link
        $('a[href="[privacy_policy]"], a[href*="\[privacy_policy\]"]').attr('href', wp_vars.files.privacy_policy);
        $('a[href="[terms_and_conditions]"], a[href*="\[terms_and_conditions\]"]').attr('href', wp_vars.files.terms_and_conditions);

        let browserLanguage = navigator.language;
        if (!browserLanguage) {
          browserLanguage = 'en';
        } else {
          browserLanguage = navigator.language.substring(0, 2);
        }
        // const siteLanguage = document.querySelector('html').getAttribute('lang');
        const siteLanguage = $("#language-switcher").html() === 'EN' ? 'pt' : 'en';

        const languageRedirect = localStorage.getItem('manualLanguageRedirect');

        if (siteLanguage !== 'en' && browserLanguage !== siteLanguage && languageRedirect !== 'true') {
          if (!document.querySelector('body').classList.contains('single-order')) {
            window.location.href = $("#language-switcher").attr('href');
          }
        }

        $("#language-switcher").on('click', function (e) {
          e.preventDefault();
          localStorage.setItem('manualLanguageRedirect', 'true');
          window.location = $(this).attr("href");
        });
      },
      finalize: function () {
        // JavaScript to be fired on all pages, after page specific JS is fired
      }
    },
    'single_auction': {
      init: function () {
        SingleAuction.init();
      }
    },
    'single_lot': {
      init: function () {
        SingleLot.init();
      }
    },
    'post_type_archive_auction': {
      init: function () {
        ArchiveAuction.init();
      }
    },
    'myveritas': {
      init: function () {
        MyVeritas.init();
      }
    },
    'myveritas_login': {
      init: function () {
        LoginPage.init();
      }
    },
    'myveritas_register': {
      init: function () {
        RegistrationPage.init();
      }
    },
    'myveritas_profile': {
      init: function () {
        ProfilePage.init();
      }
    },
    'myveritas_reset_password': {
      init: function () {
        ResetPasswordForm.init();
      }
    },
    'myveritas_delete_account': {
      init: function () {
        DeleteAccountForm.init();
      }
    },
    'myveritas_order': {
      init: function () {
        Order.init();
      }
    },
    'myveritas_order_submit': {
      init: function () {
        OrderSubmit.init();
      }
    },
    'myveritas_order_edit': {
      init: function () {
        OrderEdit.init();
      }
    }


  };

  // The routing fires all common scripts, followed by the page specific scripts.
  // Add additional events for more control over timing e.g. a finalize event
  var UTIL = {
    fire: function (func, funcname, args) {
      var fire;
      var namespace = Sage;
      funcname = (funcname === undefined) ? 'init' : funcname;
      fire = func !== '';
      fire = fire && namespace[func];
      fire = fire && typeof namespace[func][funcname] === 'function';

      if (fire) {
        namespace[func][funcname](args);
      }
    },
    loadEvents: function () {
      // Fire common init JS
      UTIL.fire('common');

      // Fire page-specific init JS, and then finalize JS
      $.each(document.body.className.replace(/-/g, '_').split(/\s+/), function (i, classnm) {
        UTIL.fire(classnm);
        UTIL.fire(classnm, 'finalize');
      });

      // Fire common finalize JS
      UTIL.fire('common', 'finalize');
    }
  };

  // Load Events
  $(document).ready(UTIL.loadEvents);

})(jQuery); // Fully reference jQuery after this point.

//# sourceMappingURL=main.js.map
