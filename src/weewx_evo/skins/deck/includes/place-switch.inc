#errorCatcher Echo
#encoding UTF-8
##
## The row of places in the head of every place page.
##
## **It goes to the counterpart page.** Somebody switching place on the week
## page means "this, over there"; sending them to `index.html` loses where
## they were, which on a phone is a scroll back to it. The same reasoning the
## unit switch already carries -- except that here the renderer works the
## address out, so it is in the file before any script runs.
##
## **And it never produces a 404.** `$places_here` is the roster filtered to
## the places whose own archive covers *this page's* span, and the same test
## decided whether that file was written at all. A place that has no May 2026
## is simply not offered one.
##
## Links, not buttons: this is navigation, and it works with scripting off.
#if $places_here
<nav class="place-switch" aria-label="$gettext('Place')">
  <!--prettier-ignore-->
  #for $p in $places_here
  <a href="$get_base_path(path=$p.path + $filename)" style="--place: $p.color"#if $p.here then ' aria-current="page"' else ''#>
    <span class="place-dot" aria-hidden="true"></span>$p.code
    <span class="visually-hidden">$p.label</span>
  </a>
  #end for
  <!--prettier-ignore-->
  ## The way up. No breadcrumb beside it: two ways up in one header is one
  ## too many.
  <a class="place-switch__all" href="$get_base_path(path='index.html')">$gettext("All places")</a>
</nav>
#end if
