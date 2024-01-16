git filter-branch --env-filter '
      if test "$GIT_AUTHOR_EMAIL" = "hungryAdmiral0512@gmail.com"
      then
              GIT_AUTHOR_EMAIL=dreamsky0701@hotmail.com
              GIT_AUTHOR_NAME="Vegetable Destroyer"
      fi
      if test "$GIT_COMMITTER_EMAIL" = "hungryAdmiral0512@gmail.com"
      then
              GIT_COMMITTER_EMAIL=dreamsky0701@hotmail.com
              GIT_AUTHOR_NAME="Vegetable Destroyer"
      fi
      ' -- --all